export interface GhStatus {
  installed: boolean;
  version: string | null;
  authenticated: boolean;
  username: string | null;
  error: string | null;
}

export interface SelectedAttachment {
  path: string;
  kind: "file" | "directory";
}
