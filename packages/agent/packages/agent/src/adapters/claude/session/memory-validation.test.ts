import { spawnSync } from "node:child_process";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import {
  serializeValidation,
  validationCommandKey,
  validationLockPrefix,
} from "./memory-validation";

describe("validationCommandKey", () => {
  it.each([
    [
      "pnpm --filter=frontend typescript:check 2>&1 | tail -8",
      "pnpm --filter=frontend typescript:check",
    ],
    [
      "cd /tmp/project && pnpm test src/small.test.ts",
      "cd /tmp/project && pnpm test src/small.test.ts",
    ],
    ["uv run pytest tests/unit", "uv run pytest tests/unit"],
    ["cargo test --jobs 1", "cargo test --jobs 1"],
    ["go build ./cmd/demo", "go build ./cmd/demo"],
    ...[
      "timeout 90s pnpm --filter=frontend typescript:check",
      "timeout --signal TERM --kill-after=5s 2m pnpm test",
      "env CI=1 timeout -k 5s 2m npx --no-install tsgo --noEmit",
      "cd frontend && npx -y --package typescript tsc --noEmit",
      "hogli test tests/unit",
      ".codex/with-flox hogli test tests/unit",
      'flox activate -- bash -c "pnpm test tests/unit"',
      "flox activate --dir . -- bash -lc 'cd frontend && npx tsgo --noEmit'",
      "bash -c 'pnpm test tests/unit | tail -10'",
      'bash -c "pnpm test \\"tests/with spaces.test.ts\\""',
      'env CI=1 pnpm test "tests/a;b.test.ts"',
      "/usr/bin/timeout 1m /usr/bin/npx tsgo --noEmit",
      'echo "example; pnpm test" && pnpm build',
      "pnpm --filter @example/tasks run backend:test",
      "timeout 1m pnpm backend:test",
      "pnpm --filter @example/storybook build-storybook",
      "pnpm turbo run lint backend:test --filter=@example/tasks",
      "pnpm -w backend:test",
      "npm run --workspace @example/tasks backend:test",
      "npm exec -- tsc --noEmit",
      "pnpm exec tsgo --noEmit",
      "timeout 90s \\\n  pnpm test",
      "cd frontend && \\\n  pnpm test",
      "uv run \\\n  pytest tests/unit",
      "npx \\\n  tsgo --noEmit",
      'bash -c "pnpm \\\n test"',
      "pn\\\npm test",
      'result="$(pnpm test)"',
      'echo "$(pnpm test)"',
      'echo "$(echo "$(pnpm test)")"',
      "result=`pnpm test`",
      'echo "`pnpm test`"',
      "cat <<'EOF'\npnpm build\nEOF\npnpm test",
      "cat <<-EOF\n\tpnpm build\n\tEOF\npnpm test",
      "cat <<FIRST <<'SECOND'\npnpm build\nFIRST\nnpx tsgo\nSECOND\npnpm test",
      "cat <<EOF | cat\nliteral\nEOF\npnpm test",
    ].map((command): [string, string] => [command, command]),
    [
      "timeout 1m npx tsgo --noEmit 2>&1 | tail -5",
      "timeout 1m npx tsgo --noEmit",
    ],
    ["hogli test tests/unit > /tmp/results.log &", "hogli test tests/unit"],
    [
      'out="$(pnpm test 2>&1)"; echo "$out" | tail -20',
      'out="$(pnpm test 2>&1)"',
    ],
    ["cat <<EOF\npnpm build\nEOF\ngit status", undefined],
    ["cat <<EOF\npnpm test", undefined],
    ["cat <<< 'pnpm test'", undefined],
    ["echo '$(pnpm test)'", undefined],
    ["echo '`pnpm test`'", undefined],
    ['echo "\\$(pnpm test)"', undefined],
    ["'pn\\\npm' test", undefined],
    ["npm exec -- echo test", undefined],
    ["pnpm --filter test run start", undefined],
    ["npm run --workspace test start", undefined],
    ["pnpm run start test", undefined],
    ["pnpm turbo run lint --filter test", undefined],
    [
      "pnpm test > /tmp/results.log tests/unit",
      "pnpm test > /tmp/results.log tests/unit",
    ],
    ["git status", undefined],
    ['echo "pnpm test"', undefined],
    ['echo "example; pnpm test"', undefined],
    ["printf '%s\\n' 'timeout 1m npx tsgo --noEmit'", undefined],
    ["# pnpm test\ngit status", undefined],
    ["cat <<'EOF'\npnpm test\nEOF", undefined],
    ["bash /tmp/check.sh", undefined],
    ["bash -c 'echo \"example; pnpm test\"'", undefined],
    ["timeout 1m echo pnpm test", undefined],
    ["npx --yes prettier --check .", undefined],
    ["flox activate -- bash -c 'git status'", undefined],
    ["hogli status", undefined],
    ["cat test-output.txt", undefined],
  ])("recognizes validation scope in %s", (command, expected) => {
    expect(validationCommandKey(command)).toBe(expected);
    if (expected) {
      expect(validationCommandKey(serializeValidation(command))).toBe(expected);
    }
  });
});

describe.runIf(process.platform === "linux")("validationLockPrefix", () => {
  const gib = 1024 ** 3;

  it.each([
    [16 * gib, 13 * gib, 75, "", /has 0\.6 GiB of memory left/],
    [16 * gib, 8 * gib, 0, "ran\n", /^$/],
    [2 * gib, gib / 2, 0, "ran\n", /^$/],
  ])(
    "with a %d byte limit and %d bytes in use exits %d",
    (limit, current, status, stdout, stderr) => {
      const root = mkdtempSync(join(tmpdir(), "validation-lock-"));
      try {
        mkdirSync(join(root, "tmp"));
        mkdirSync(join(root, "sys/fs/cgroup"), { recursive: true });
        writeFileSync(join(root, "sys/fs/cgroup/memory.max"), `${limit}\n`);
        writeFileSync(
          join(root, "sys/fs/cgroup/memory.current"),
          `${current}\n`,
        );
        const result = spawnSync(
          "bash",
          ["-c", `${validationLockPrefix(root)}echo ran`],
          { encoding: "utf8" },
        );
        expect(result).toMatchObject({ status, stdout });
        expect(result.stderr).toMatch(stderr);
        if (status !== 0) {
          expect(
            result.stderr.match(/GiB {2}\S.* \(pid \d+\)$/gm),
          ).toHaveLength(3);
        }
      } finally {
        rmSync(root, { recursive: true, force: true });
      }
    },
  );
});
