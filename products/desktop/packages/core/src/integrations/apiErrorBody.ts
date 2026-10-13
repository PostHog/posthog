export interface ApiErrorBody {
  code: string | null;
  detail: string | null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

/** Read the stable string fields from an API error without leaking casts. */
export function readApiErrorBody(error: unknown): ApiErrorBody {
  const body = isRecord(error) && isRecord(error.body) ? error.body : null;
  return {
    code: typeof body?.code === "string" ? body.code : null,
    detail: typeof body?.detail === "string" ? body.detail : null,
  };
}
