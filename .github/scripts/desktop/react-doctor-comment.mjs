import fs from "node:fs";

const [reportPath, outPath] = process.argv.slice(2);
const MARKER = "<!-- desktop-react-doctor:summary -->";
const slug = process.env.GITHUB_REPOSITORY;
// The scan runs with cwd=products/desktop, so report paths are relative to it;
// blob links need the repo-root path back.
const rawPrefix = process.env.REACT_DOCTOR_PATH_PREFIX || "";
const pathPrefix =
  rawPrefix && !rawPrefix.endsWith("/") ? `${rawPrefix}/` : rawPrefix;
const server = (process.env.GITHUB_SERVER_URL || "https://github.com").replace(
  /\/$/,
  "",
);
const head = (
  process.env.REACT_DOCTOR_HEAD_SHA ||
  process.env.GITHUB_SHA ||
  ""
).trim();

const MAX_LISTED = 50;
const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;
const inline = (value) =>
  String(value ?? "")
    .replace(/\s+/g, " ")
    .replace(/[`<>]/g, "")
    .trim();
const byFileThenLine = (a, b) =>
  a.filePath === b.filePath
    ? a.line - b.line
    : a.filePath < b.filePath
      ? -1
      : 1;
const encodedPath = (file) =>
  String(file ?? "")
    .split("/")
    .map((segment) =>
      encodeURIComponent(segment).replace(/[()]/g, (c) =>
        c === "(" ? "%28" : "%29",
      ),
    )
    .join("/");
const fileLink = (file, line) =>
  slug && head
    ? `[\`${inline(file)}:${line}\`](${server}/${slug}/blob/${head}/${encodedPath(pathPrefix + file)}#L${line})`
    : `\`${inline(file)}:${line}\``;

let report;
try {
  report = JSON.parse(fs.readFileSync(reportPath, "utf8"));
} catch {
  report = null;
}

const lines = [MARKER, ""];

if (!report) {
  lines.push("**React Doctor** could not produce a report.");
} else if (!report.ok) {
  lines.push(
    "**React Doctor** could not complete this scan.",
    "",
    `> ${inline(report.error?.message) || "scan failed"}`,
  );
} else {
  const summary = report.summary ?? {};
  const total = summary.totalDiagnosticCount ?? 0;
  // Diagnostic filePaths are relative to their project (e.g. apps/mobile), not
  // the scan root; rejoin them so labels and blob links resolve.
  const scanRoot = String(report.directory ?? "").replace(/\/+$/, "");
  const diagnostics = (report.projects ?? []).flatMap((project) => {
    const dir = String(project.directory ?? "");
    const projectRel =
      scanRoot && dir.startsWith(scanRoot)
        ? dir.slice(scanRoot.length).replace(/^\/+/, "")
        : "";
    return (project.diagnostics ?? []).map((diagnostic) => ({
      ...diagnostic,
      filePath: projectRel
        ? `${projectRel}/${diagnostic.filePath}`
        : diagnostic.filePath,
    }));
  });

  if (total === 0) {
    lines.push("**React Doctor** found no issues in the changed files. 🎉");
  } else {
    const severity = [];
    if (summary.errorCount) severity.push(plural(summary.errorCount, "error"));
    if (summary.warningCount)
      severity.push(plural(summary.warningCount, "warning"));
    const severityTail = severity.length ? ` · ${severity.join(" & ")}` : "";
    lines.push(
      `**React Doctor** found **${plural(total, "issue")}** in ${plural(summary.affectedFileCount ?? 0, "file")}${severityTail}.`,
    );

    const errors = diagnostics
      .filter((d) => d.severity === "error")
      .sort(byFileThenLine);
    if (errors.length) {
      lines.push("", "**Errors**", "");
      for (const error of errors.slice(0, MAX_LISTED)) {
        const title = inline(error.title);
        lines.push(
          `- ❌ ${fileLink(error.filePath, error.line)}${title ? ` ${title}` : ""} \`${inline(error.rule)}\``,
        );
      }
      if (errors.length > MAX_LISTED)
        lines.push(
          "",
          `${plural(errors.length - MAX_LISTED, "more error")} not shown.`,
        );
    }

    const warnings = diagnostics
      .filter((d) => d.severity === "warning")
      .sort(byFileThenLine);
    if (warnings.length) {
      lines.push(
        "",
        `<details><summary>${plural(warnings.length, "warning")}</summary>`,
        "",
      );
      let currentFile = null;
      for (const warning of warnings.slice(0, MAX_LISTED)) {
        if (warning.filePath !== currentFile) {
          if (currentFile !== null) lines.push("");
          lines.push(`**\`${inline(warning.filePath)}\`**`);
          currentFile = warning.filePath;
        }
        const title = inline(warning.title);
        lines.push(
          `- ⚠️ ${fileLink(warning.filePath, warning.line)}${title ? ` ${title}` : ""} \`${inline(warning.rule)}\``,
        );
      }
      if (warnings.length > MAX_LISTED)
        lines.push(
          "",
          `${plural(warnings.length - MAX_LISTED, "more warning")} not shown.`,
        );
      lines.push("", "</details>");
    }
  }
}

const commit = head ? ` for commit \`${head.slice(0, 7)}\`` : "";
lines.push(
  "",
  `<sub>Reviewed by [React Doctor](https://react.doctor)${commit}.</sub>`,
);

fs.writeFileSync(
  outPath,
  `${lines
    .join("\n")
    .replace(/\n{3,}/g, "\n\n")
    .trimEnd()}\n`,
);
