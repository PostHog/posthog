export interface TokenRule {
  label: string;
  prefix: string;
  body: RegExp;
  // Replaces prefix and body for a complete string. Streamed chunks keep the prefix,
  // because a chunk can end before the part of the token that the shape requires.
  shape?: RegExp;
  bodyLength?: number;
  /** The prefix also ends ordinary words ("alpha_"), so it must start one. */
  wordStart?: boolean;
}

const URL_SAFE_BODY = /[A-Za-z0-9_-]/;

export const TOKEN_RULES: TokenRule[] = [
  {
    label: "claude oauth token",
    prefix: "sk-ant-oat01-",
    body: URL_SAFE_BODY,
  },
  {
    label: "anthropic api key",
    prefix: "sk-ant-api",
    body: URL_SAFE_BODY,
  },
  {
    label: "github installation token",
    prefix: "ghs_",
    body: URL_SAFE_BODY,
  },
  {
    label: "github personal access token",
    prefix: "ghp_",
    body: URL_SAFE_BODY,
  },
  {
    label: "github fine-grained token",
    prefix: "github_pat_",
    body: URL_SAFE_BODY,
  },
  {
    label: "posthog personal api key",
    prefix: "phx_",
    body: URL_SAFE_BODY,
  },
  {
    // A ChatGPT access token is a JWT; "eyJ" is base64 for the opening of its JSON header.
    label: "jwt",
    prefix: "eyJ",
    body: /[A-Za-z0-9_.-]/,
    // The prefix also occurs inside random identifiers such as a tool call id. A dot
    // does not, and a JWT always has one after its header.
    shape: /eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-][A-Za-z0-9_.-]*/,
  },
  {
    label: "posthog oauth access token",
    prefix: "pha_",
    body: URL_SAFE_BODY,
    wordStart: true,
  },
  {
    label: "posthog oauth refresh token",
    prefix: "phr_",
    body: URL_SAFE_BODY,
    wordStart: true,
  },
  {
    label: "posthog ai gateway session token",
    prefix: "phe_",
    body: URL_SAFE_BODY,
    wordStart: true,
  },
  {
    label: "github oauth access token",
    prefix: "gho_",
    body: URL_SAFE_BODY,
    wordStart: true,
  },
  {
    label: "github user-to-server token",
    prefix: "ghu_",
    body: URL_SAFE_BODY,
    wordStart: true,
  },
  {
    label: "github refresh token",
    prefix: "ghr_",
    body: URL_SAFE_BODY,
    wordStart: true,
  },
  {
    label: "openai project api key",
    prefix: "sk-proj-",
    body: URL_SAFE_BODY,
    wordStart: true,
  },
  {
    label: "aws access key id",
    prefix: "AKIA",
    body: /[A-Z0-9]/,
    bodyLength: 16,
    wordStart: true,
  },
  {
    label: "aws temporary access key id",
    prefix: "ASIA",
    body: /[A-Z0-9]/,
    bodyLength: 16,
    wordStart: true,
  },
  {
    label: "slack bot token",
    prefix: "xoxb-",
    body: URL_SAFE_BODY,
    wordStart: true,
  },
  {
    label: "slack user token",
    prefix: "xoxp-",
    body: URL_SAFE_BODY,
    wordStart: true,
  },
  {
    label: "slack legacy workspace token",
    prefix: "xoxa-",
    body: URL_SAFE_BODY,
    wordStart: true,
  },
  {
    label: "slack refresh token",
    prefix: "xoxr-",
    body: URL_SAFE_BODY,
    wordStart: true,
  },
  {
    label: "slack legacy session token",
    prefix: "xoxs-",
    body: URL_SAFE_BODY,
    wordStart: true,
  },
  {
    label: "slack rotation refresh token",
    prefix: "xoxe-",
    body: URL_SAFE_BODY,
    wordStart: true,
  },
  {
    label: "gitlab personal access token",
    prefix: "glpat-",
    body: URL_SAFE_BODY,
    wordStart: true,
  },
];

export const LOOPBACK_PROXY_TOKEN =
  /(\/\/(?:127\.0\.0\.1|localhost|\[::1\]):\d+\/)[A-Za-z0-9_-]{32}[A-Za-z0-9_-]*/g;

export const SECRET_HEADERS: string[] = [
  "authorization",
  "proxy-authorization",
  "x-api-key",
];
