import { readFile, rm } from "node:fs/promises";
import { z } from "zod/v4";
import { mcpServersSchema } from "./schemas";

const deferredCredentialsSchema = z.object({
  mcpServers: mcpServersSchema.optional(),
  eventIngestToken: z.string().min(1).optional(),
  taskRunSessionToken: z.string().min(1).optional(),
});

export type DeferredCredentials = z.output<typeof deferredCredentialsSchema>;

export async function consumeDeferredCredentials(
  path: string | undefined,
): Promise<DeferredCredentials | null> {
  if (!path) return null;
  const raw = await readFile(path, "utf8");
  try {
    return deferredCredentialsSchema.parse(JSON.parse(raw));
  } finally {
    await rm(path, { force: true });
  }
}
