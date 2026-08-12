import { angular } from "@codemirror/lang-angular";
import { cpp } from "@codemirror/lang-cpp";
import { css } from "@codemirror/lang-css";
import { go } from "@codemirror/lang-go";
import { html } from "@codemirror/lang-html";
import { java } from "@codemirror/lang-java";
import { javascript } from "@codemirror/lang-javascript";
import { jinja } from "@codemirror/lang-jinja";
import { json } from "@codemirror/lang-json";
import { liquid } from "@codemirror/lang-liquid";
import { markdown } from "@codemirror/lang-markdown";
import { php } from "@codemirror/lang-php";
import { python } from "@codemirror/lang-python";
import { rust } from "@codemirror/lang-rust";
import { sass } from "@codemirror/lang-sass";
import { sql } from "@codemirror/lang-sql";
import { vue } from "@codemirror/lang-vue";
import { wast } from "@codemirror/lang-wast";
import { xml } from "@codemirror/lang-xml";
import { yaml } from "@codemirror/lang-yaml";
import type { Extension } from "@codemirror/state";

type LanguageExtension = () => Extension;

const LANGUAGE_MAP: Record<string, LanguageExtension> = {
  // JavaScript/TypeScript
  js: () => javascript({ jsx: true }),
  jsx: () => javascript({ jsx: true }),
  mjs: () => javascript(),
  ts: () => javascript({ jsx: true, typescript: true }),
  tsx: () => javascript({ jsx: true, typescript: true }),

  // Web
  html: html,
  htm: html,
  css: css,
  scss: () => sass({ indented: false }),
  sass: () => sass({ indented: true }),
  vue: vue,
  component: angular,

  // Data formats
  json: json,
  xml: xml,
  svg: xml,
  yaml: yaml,
  yml: yaml,

  // Programming languages
  py: python,
  rs: rust,
  go: go,
  java: java,
  cpp: cpp,
  c: cpp,
  h: cpp,
  hpp: cpp,
  php: php,
  sql: sql,
  wast: wast,
  wat: wast,

  // Templates
  jinja: jinja,
  jinja2: jinja,
  j2: jinja,
  liquid: liquid,

  // Docs
  md: markdown,
  markdown: markdown,
};

export function getLanguageExtension(filePath: string): Extension | null {
  const ext = filePath.split(".").pop()?.toLowerCase();
  if (!ext) return null;

  const factory = LANGUAGE_MAP[ext];
  return factory ? factory() : null;
}
