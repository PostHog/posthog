import jwt from "jsonwebtoken";
import { z } from "zod";

export const SANDBOX_CONNECTION_AUDIENCE = "posthog:sandbox_connection";

export const userDataSchema = z.object({
  run_id: z.string(),
  task_id: z.string(),
  team_id: z.number(),
  user_id: z.number(),
  distinct_id: z.string(),
  mode: z.enum(["interactive", "background"]).optional().default("interactive"),
});

const jwtPayloadSchema = userDataSchema.extend({
  exp: z.number(),
  iat: z.number().optional(),
  aud: z.string().optional(),
});

export type JwtPayload = z.infer<typeof userDataSchema>;

export class JwtValidationError extends Error {
  constructor(
    message: string,
    public code:
      | "invalid_token"
      | "expired"
      | "invalid_signature"
      | "server_error",
  ) {
    super(message);
    this.name = "JwtValidationError";
  }
}

export function validateJwt(token: string, publicKey: string): JwtPayload {
  try {
    const decoded = jwt.verify(token, publicKey, {
      algorithms: ["RS256"],
      audience: SANDBOX_CONNECTION_AUDIENCE,
    });

    const result = jwtPayloadSchema.safeParse(decoded);
    if (!result.success) {
      throw new JwtValidationError(
        `Missing required fields: ${result.error.message}`,
        "invalid_token",
      );
    }

    return result.data;
  } catch (error) {
    if (error instanceof JwtValidationError) {
      throw error;
    }
    if (error instanceof jwt.TokenExpiredError) {
      throw new JwtValidationError("Token expired", "expired");
    }
    if (error instanceof jwt.JsonWebTokenError) {
      throw new JwtValidationError("Invalid signature", "invalid_signature");
    }
    throw new JwtValidationError("Invalid token", "invalid_token");
  }
}
