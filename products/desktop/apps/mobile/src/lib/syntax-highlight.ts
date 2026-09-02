import hljs from "highlight.js/lib/core";
import cpp from "highlight.js/lib/languages/cpp";
import css from "highlight.js/lib/languages/css";
import go from "highlight.js/lib/languages/go";
import java from "highlight.js/lib/languages/java";
import javascript from "highlight.js/lib/languages/javascript";
import json from "highlight.js/lib/languages/json";
import markdown from "highlight.js/lib/languages/markdown";
import php from "highlight.js/lib/languages/php";
import python from "highlight.js/lib/languages/python";
import ruby from "highlight.js/lib/languages/ruby";
import rust from "highlight.js/lib/languages/rust";
import scss from "highlight.js/lib/languages/scss";
import shell from "highlight.js/lib/languages/shell";
import sql from "highlight.js/lib/languages/sql";
import swift from "highlight.js/lib/languages/swift";
import typescript from "highlight.js/lib/languages/typescript";
import xml from "highlight.js/lib/languages/xml";
import yaml from "highlight.js/lib/languages/yaml";

hljs.registerLanguage("cpp", cpp);
hljs.registerLanguage("c", cpp);
hljs.registerLanguage("css", css);
hljs.registerLanguage("go", go);
hljs.registerLanguage("golang", go);
hljs.registerLanguage("java", java);
hljs.registerLanguage("javascript", javascript);
hljs.registerLanguage("js", javascript);
hljs.registerLanguage("jsx", javascript);
hljs.registerLanguage("json", json);
hljs.registerLanguage("markdown", markdown);
hljs.registerLanguage("md", markdown);
hljs.registerLanguage("php", php);
hljs.registerLanguage("python", python);
hljs.registerLanguage("py", python);
hljs.registerLanguage("ruby", ruby);
hljs.registerLanguage("rb", ruby);
hljs.registerLanguage("rust", rust);
hljs.registerLanguage("rs", rust);
hljs.registerLanguage("scss", scss);
hljs.registerLanguage("sass", scss);
hljs.registerLanguage("shell", shell);
hljs.registerLanguage("bash", shell);
hljs.registerLanguage("sh", shell);
hljs.registerLanguage("zsh", shell);
hljs.registerLanguage("sql", sql);
hljs.registerLanguage("swift", swift);
hljs.registerLanguage("typescript", typescript);
hljs.registerLanguage("ts", typescript);
hljs.registerLanguage("tsx", typescript);
hljs.registerLanguage("xml", xml);
hljs.registerLanguage("html", xml);
hljs.registerLanguage("svg", xml);
hljs.registerLanguage("yaml", yaml);
hljs.registerLanguage("yml", yaml);

export interface HighlightSegment {
  text: string;
  className?: string;
}

// One Dark palette matching the desktop app
const ONE_DARK_COLORS: Record<string, string> = {
  "hljs-keyword": "#c678dd",
  "hljs-built_in": "#e5c07b",
  "hljs-type": "#e5c07b",
  "hljs-literal": "#d19a66",
  "hljs-number": "#d19a66",
  "hljs-string": "#98c379",
  "hljs-regexp": "#56b6c2",
  "hljs-comment": "#8a8275",
  "hljs-doctag": "#c678dd",
  "hljs-function": "#61afef",
  "hljs-title": "#61afef",
  "hljs-title.function_": "#61afef",
  "hljs-params": "#c4baa8",
  "hljs-variable": "#e06c75",
  "hljs-attr": "#d19a66",
  "hljs-attribute": "#d19a66",
  "hljs-name": "#e06c75",
  "hljs-tag": "#e06c75",
  "hljs-selector-tag": "#e06c75",
  "hljs-selector-class": "#e5c07b",
  "hljs-selector-id": "#61afef",
  "hljs-property": "#e06c75",
  "hljs-meta": "#56b6c2",
  "hljs-operator": "#56b6c2",
  "hljs-punctuation": "#c4baa8",
  "hljs-subst": "#c4baa8",
  "hljs-symbol": "#56b6c2",
  "hljs-addition": "#98c379",
  "hljs-deletion": "#e06c75",
};

function decodeEntities(text: string): string {
  // Decode &amp; last to avoid double-unescaping (e.g. &amp;lt; → &lt; → <)
  return text
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#x27;/g, "'")
    .replace(/&#39;/g, "'")
    .replace(/&amp;/g, "&");
}

/**
 * Parse highlight.js HTML output into segments.
 * Input: `<span class="hljs-keyword">const</span> x = <span ...>42</span>;`
 */
function parseHljsHtml(html: string): HighlightSegment[] {
  const segments: HighlightSegment[] = [];
  const regex = /<span class="([^"]*)">([\s\S]*?)<\/span>|([^<]+)/g;

  for (let match = regex.exec(html); match !== null; match = regex.exec(html)) {
    if (match[3]) {
      segments.push({ text: decodeEntities(match[3]) });
    } else if (match[1] && match[2] !== undefined) {
      const className = match[1];
      const inner = match[2];
      if (inner.includes("<span")) {
        for (const nested of parseHljsHtml(inner)) {
          segments.push({
            text: nested.text,
            className: nested.className ?? className,
          });
        }
      } else {
        segments.push({ text: decodeEntities(inner), className });
      }
    }
  }

  return segments;
}

export function highlightCode(
  code: string,
  language: string,
): HighlightSegment[] | null {
  if (!hljs.getLanguage(language)) return null;

  try {
    const result = hljs.highlight(code, { language });
    return parseHljsHtml(result.value);
  } catch {
    return null;
  }
}

export function getColorForClass(className?: string): string | undefined {
  if (!className) return undefined;
  return ONE_DARK_COLORS[className] ?? ONE_DARK_COLORS[className.split(" ")[0]];
}

const EXT_TO_LANGUAGE: Record<string, string> = {
  ts: "typescript",
  tsx: "typescript",
  js: "javascript",
  jsx: "javascript",
  mjs: "javascript",
  cjs: "javascript",
  py: "python",
  go: "go",
  rs: "rust",
  rb: "ruby",
  java: "java",
  c: "c",
  cpp: "cpp",
  h: "cpp",
  hpp: "cpp",
  css: "css",
  scss: "scss",
  html: "html",
  xml: "xml",
  svg: "xml",
  json: "json",
  yaml: "yaml",
  yml: "yaml",
  md: "markdown",
  sql: "sql",
  sh: "shell",
  bash: "shell",
  zsh: "shell",
  swift: "swift",
  php: "php",
};

export function languageFromPath(filePath: string): string | null {
  const ext = filePath.split(".").pop()?.toLowerCase();
  if (!ext) return null;
  return EXT_TO_LANGUAGE[ext] ?? null;
}
