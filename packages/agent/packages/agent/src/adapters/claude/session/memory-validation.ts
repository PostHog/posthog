function shellGroupEnd(
  command: string,
  start: number,
  close: string,
  depth = 0,
): number {
  if (depth >= 32) return command.length;
  for (let index = start; index < command.length; index++) {
    const char = command[index];
    if (char === "\\" && close !== "'") {
      index++;
    } else if (char === close) {
      return index + 1;
    } else if (close !== "'") {
      if (command.startsWith("$(", index)) {
        index = shellGroupEnd(command, index + 2, ")", depth + 1) - 1;
      } else if (char === "`" || (close === ")" && /['"(]/.test(char))) {
        index =
          shellGroupEnd(
            command,
            index + 1,
            char === "(" ? ")" : char,
            depth + 1,
          ) - 1;
      }
    }
  }
  return command.length;
}

function shellWordEnd(command: string, start: number): number {
  let index = start;
  while (index < command.length && !/[\s;&|()<>]/.test(command[index])) {
    const char = command[index];
    if (char === "\\") {
      index += 2;
    } else if (command.startsWith("$(", index)) {
      index = shellGroupEnd(command, index + 2, ")");
    } else if (/["'`]/.test(char)) {
      index = shellGroupEnd(command, index + 1, char);
    } else {
      index++;
    }
  }
  return index;
}

function hasValidationSubstitution(word: string, depth: number): boolean {
  let doubleQuoted = false;
  for (let index = 0; index < word.length; index++) {
    const char = word[index];
    if (char === "\\") {
      index++;
    } else if (char === "'" && !doubleQuoted) {
      index = shellGroupEnd(word, index + 1, "'") - 1;
    } else if (char === '"') {
      doubleQuoted = !doubleQuoted;
    } else if (char === "`" || word.startsWith("$(", index)) {
      const start = index + (char === "`" ? 1 : 2);
      const end = shellGroupEnd(word, start, char === "`" ? "`" : ")");
      if (
        validationCommandEnd(word.slice(start, end - 1), depth + 1) !==
        undefined
      )
        return true;
      index = end - 1;
    }
  }
  return false;
}

function unquote(word: string): string {
  return word.replace(
    /'([^']*)'|"((?:\\[\s\S]|[^"\\])*)"|\\([\s\S])/g,
    (
      _,
      single: string | undefined,
      double: string | undefined,
      escaped: string,
    ) =>
      single ??
      double?.replace(/\\([$`"\\\n])/g, (_, char: string) =>
        char === "\n" ? "" : char,
      ) ??
      (escaped === "\n" ? "" : escaped),
  );
}

function skipOptions(words: string[], valueOptions: string[] = []): string[] {
  let index = 0;
  while (words[index]?.startsWith("-")) {
    const option = words[index++];
    if (option === "--") break;
    if (valueOptions.includes(option)) index++;
  }
  return words.slice(index);
}

function isValidationScript(script: string | undefined): boolean {
  return /(?:^|[:-])(?:test|build|typecheck|typescript:check)(?:[:-]|$)/.test(
    script ?? "",
  );
}

function isValidationCommand(words: string[], depth: number): boolean {
  if (depth >= 8 || words.length === 0) return false;
  const [head, ...args] = words;
  const executable = head.split("/").at(-1);
  if (/^[A-Za-z_]\w*=/.test(head)) {
    return isValidationCommand(args, depth + 1);
  }
  switch (executable) {
    case "env":
    case "exec":
    case "time":
      return isValidationCommand(
        skipOptions(args, ["-u", "--unset", "-C", "--chdir", "-a"]),
        depth + 1,
      );
    case "timeout": {
      const [duration, ...command] = skipOptions(args, [
        "-s",
        "--signal",
        "-k",
        "--kill-after",
      ]);
      return (
        /^\d+(?:\.\d+)?[smhd]?$/.test(duration ?? "") &&
        isValidationCommand(command, depth + 1)
      );
    }
    case "npx":
      return isValidationCommand(
        skipOptions(args, ["-p", "--package"]),
        depth + 1,
      );
    case "flox": {
      const separator = args.indexOf("--");
      return (
        args[0] === "activate" &&
        separator !== -1 &&
        isValidationCommand(args.slice(separator + 1), depth + 1)
      );
    }
    case "with-flox":
      return isValidationCommand(args, depth + 1);
    case "bash":
    case "sh":
    case "zsh": {
      const index = args.findIndex((arg) => /^-[a-z]*c[a-z]*$/.test(arg));
      return (
        index !== -1 &&
        args.slice(0, index).every((arg) => /^-[a-z]+$/.test(arg)) &&
        validationCommandEnd(args[index + 1] ?? "", depth + 1) !== undefined
      );
    }
    case "uv":
      return args[0] === "run" && isValidationCommand(args.slice(1), depth + 1);
    case "pnpm":
    case "npm":
    case "yarn":
    case "bun":
    case "hogli": {
      const valueOptions = [
        "--filter",
        "--filter-prod",
        "-F",
        "--dir",
        "-C",
        "--prefix",
        "--cwd",
        "--workspace",
        ...(executable === "npm" ? ["-w"] : []),
      ];
      const command = skipOptions(args, valueOptions);
      if (["exec", "dlx", "x", "turbo"].includes(command[0])) {
        return isValidationCommand(
          command[0] === "turbo"
            ? command
            : skipOptions(command.slice(1), ["-p", "--package"]),
          depth + 1,
        );
      }
      const script =
        command[0] === "run"
          ? skipOptions(command.slice(1), valueOptions)[0]
          : command[0];
      return isValidationScript(script);
    }
    case "turbo": {
      let tasks = args;
      while (tasks.length) {
        const [task, ...rest] = skipOptions(tasks, [
          "--filter",
          "--cwd",
          "--concurrency",
        ]);
        if (isValidationScript(task)) return true;
        tasks = rest;
      }
      return false;
    }
    case "pytest":
    case "jest":
    case "vitest":
    case "tsc":
    case "tsgo":
      return true;
    case "cargo":
    case "go":
      return /^(?:test|build|check)$/.test(args[0] ?? "");
    default:
      return false;
  }
}

function validationCommandEnd(command: string, depth = 0): number | undefined {
  if (depth >= 8) return undefined;
  let words: string[] = [];
  let end = 0;
  let redirectTarget = false;
  let substitution = false;
  let heredoc: boolean | undefined;
  const heredocs: { delimiter: string; stripTabs: boolean }[] = [];
  for (let index = 0; index <= command.length; ) {
    const operator =
      /^(?:#[^\n]*|\d*(?:<<<|<<-?|[<>]+)(?:&\d+)?|[;&|()\n])/.exec(
        command.slice(index),
      );
    if (/[^\S\n]/.test(command[index] ?? "")) {
      index++;
      continue;
    }
    const next = operator
      ? index + operator[0].length
      : shellWordEnd(command, index);
    const raw = index === command.length ? "\n" : command.slice(index, next);
    index = next + (index === command.length ? 1 : 0);
    if (raw.startsWith("#") || /^(?:\\\n)+$/.test(raw)) continue;
    if (/^[;&|()\n]$/.test(raw)) {
      if (substitution || isValidationCommand(words, depth)) return end;
      words = [];
      redirectTarget = false;
      if (raw === "\n") {
        for (const { delimiter, stripTabs } of heredocs.splice(0)) {
          while (index < command.length) {
            const newline = command.indexOf("\n", index);
            const lineEnd = newline === -1 ? command.length : newline;
            const line = command.slice(index, lineEnd);
            index = lineEnd + 1;
            if ((stripTabs ? line.replace(/^\t+/, "") : line) === delimiter)
              break;
          }
        }
      }
    } else if (/^\d*[<>]/.test(raw)) {
      if (/^\d*<<-?$/.test(raw)) heredoc = raw.endsWith("-");
      redirectTarget = !raw.includes("&");
    } else if (heredoc !== undefined) {
      heredocs.push({ delimiter: unquote(raw), stripTabs: heredoc });
      heredoc = undefined;
      redirectTarget = false;
    } else if (redirectTarget) {
      substitution ||= hasValidationSubstitution(raw, depth);
      if (substitution) end = next;
      redirectTarget = false;
    } else {
      const word = unquote(raw);
      words.push(word);
      substitution ||= hasValidationSubstitution(raw, depth);
      end = next;
    }
  }
  return undefined;
}

export const VALIDATION_LOCK_PREFIX = [
  "exec {__posthog_validation_lock_fd}>/tmp/posthog-memory-validation.lock",
  'if ! flock -n "$__posthog_validation_lock_fd"; then',
  '  printf "%s\\n" "Another build, test suite, or typecheck is running in this sandbox. Let it finish before starting more validation, including in other worktrees." >&2',
  "  exit 75",
  "fi",
  "",
].join("\n");

export function validationCommandKey(command: string): string | undefined {
  const original = command.startsWith(VALIDATION_LOCK_PREFIX)
    ? command.slice(VALIDATION_LOCK_PREFIX.length)
    : command;
  const end = validationCommandEnd(original);
  return end === undefined ? undefined : original.slice(0, end).trim();
}

export function serializeValidation(command: string): string {
  return command.startsWith(VALIDATION_LOCK_PREFIX)
    ? command
    : VALIDATION_LOCK_PREFIX + command;
}
