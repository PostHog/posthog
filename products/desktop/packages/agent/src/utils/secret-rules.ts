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
];

export const SECRET_HEADERS: string[] = [
  "authorization",
  "proxy-authorization",
  "x-api-key",
];
