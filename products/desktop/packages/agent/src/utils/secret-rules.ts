export interface TokenRule {
  label: string;
  prefix: string;
  body: RegExp;
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
];

export const LOOPBACK_PROXY_TOKEN =
  /(\/\/(?:127\.0\.0\.1|localhost|\[::1\]):\d+\/)[A-Za-z0-9_-]{32}[A-Za-z0-9_-]*/g;

export const SECRET_HEADERS: string[] = [
  "authorization",
  "proxy-authorization",
  "x-api-key",
];
