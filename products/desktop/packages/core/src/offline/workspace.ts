import { z } from "zod";

const envelope = z.object({
  version: z.literal(1),
  savedAt: z.number().finite(),
  value: z.unknown(),
});

export interface WorkspaceStorage {
  read(key: string): Promise<string | null>;
  write(key: string, value: string): Promise<void>;
  remove(key: string): Promise<void>;
}

export class OfflineWorkspace {
  private pending = Promise.resolve();
  private closed = false;

  constructor(private readonly storage: WorkspaceStorage) {}

  async read<T>(key: string, maxAge: number): Promise<T | null> {
    await this.pending;
    if (this.closed) return null;
    const raw = await this.storage.read(key);
    if (!raw) return null;
    try {
      const saved = envelope.parse(JSON.parse(raw));
      if (Date.now() - saved.savedAt > maxAge) {
        await this.remove(key);
        return null;
      }
      return saved.value as T;
    } catch {
      return null;
    }
  }

  write(key: string, value: unknown): Promise<void> {
    if (this.closed) return Promise.reject(new Error("Workspace closed"));
    const raw = JSON.stringify({ version: 1, savedAt: Date.now(), value });
    const write = this.pending.then(() => this.storage.write(key, raw));
    this.pending = write.catch(() => {});
    return write;
  }

  remove(key: string): Promise<void> {
    if (this.closed) return Promise.resolve();
    const remove = this.pending.then(() => this.storage.remove(key));
    this.pending = remove.catch(() => {});
    return remove;
  }

  async close(): Promise<void> {
    this.closed = true;
    await this.pending;
  }
}
