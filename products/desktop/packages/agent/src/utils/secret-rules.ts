export interface TokenRule {
  label: string;
  prefix: string;
  body: RegExp;
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
];

export const SECRET_HEADERS: string[] = [
  "authorization",
  "proxy-authorization",
  "x-api-key",
];
