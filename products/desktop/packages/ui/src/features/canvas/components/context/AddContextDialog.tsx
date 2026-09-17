import {
  CheckCircleIcon,
  FileTextIcon,
  LinkIcon,
  UploadSimpleIcon,
  WarningCircleIcon,
} from "@phosphor-icons/react";
import {
  CONTEXT_OBJECT_KIND_LABELS,
  type ContextLink,
  type ContextObject,
  isHttpUrl,
  parsePostHogObjectUrl,
} from "@posthog/core/canvas/contextDocument";
import {
  fileDisplayName,
  fileNameToPath,
  isUploadableFile,
  newFileContent,
  UPLOAD_ACCEPT,
  UPLOAD_MAX_BYTES,
} from "@posthog/core/canvas/contextFiles";
import {
  type ContextSource,
  parseContextSourceInput,
} from "@posthog/core/canvas/contextSources";
import {
  Button,
  cn,
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Input,
  Text,
} from "@posthog/quill";
import type {
  ContextSourceState,
  ContextSources,
} from "@posthog/ui/features/canvas/hooks/useContextSources";
import { useNavigate } from "@tanstack/react-router";
import { type ReactNode, useId, useMemo, useRef, useState } from "react";
import { KIND_ICONS } from "./kindIcons";
import { SourceLogo } from "./SourceLogo";
import { connectLabel, unconnectedWarning } from "./sourceStatus";

export type AddContextMode = "markdown" | "link" | "upload";

const TITLES: Record<AddContextMode, string> = {
  link: "Add a link",
  markdown: "New Markdown file",
  upload: "Upload a file",
};

const SUBMIT_LABELS: Record<AddContextMode, string> = {
  link: "Add link",
  markdown: "Create and edit",
  upload: "Add file",
};

interface AddContextDialogProps {
  mode: AddContextMode;
  sources: ContextSources;
  /** Where this space's Markdown files go; null when the context wiki is not available. */
  filesFolder: string | null;
  existingTargets: readonly string[];
  onAddLink: (link: ContextLink) => Promise<void>;
  onAddObject: (object: ContextObject) => Promise<void>;
  /** Adds the file to CONTEXT.md; `content` null means the person writes it next. */
  onAddFile: (path: string, content: string | null) => Promise<void>;
  onClose: () => void;
}

/**
 * One way to add a piece of context, chosen before the dialog opens: paste a
 * link, name a Markdown file, or upload a text file. A link says what it is
 * as soon as it is pasted, so a person sees whether agents can read it before
 * adding it.
 */
export function AddContextDialog({
  mode,
  sources,
  filesFolder,
  existingTargets,
  onAddLink,
  onAddObject,
  onAddFile,
  onClose,
}: AddContextDialogProps) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [url, setUrl] = useState("");
  const [title, setTitle] = useState<string | null>(null);
  const [fileName, setFileName] = useState("");
  const [upload, setUpload] = useState<File | null>(null);

  const navigate = useNavigate();
  const detected = useMemo(() => detectLink(url, sources), [url, sources]);
  const filePath =
    filesFolder && fileName.trim()
      ? fileNameToPath(filesFolder, fileName)
      : null;
  const fileExists = filePath !== null && existingTargets.includes(filePath);
  const uploadPath =
    filesFolder && upload ? fileNameToPath(filesFolder, upload.name) : null;
  const uploadExists =
    uploadPath !== null && existingTargets.includes(uploadPath);

  const canSubmit =
    !busy &&
    (mode === "link"
      ? detected !== null && detected.kind !== "invalid"
      : mode === "markdown"
        ? filePath !== null && !fileExists
        : uploadPath !== null && !uploadExists);

  const run = async (work: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await work();
      onClose();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  };

  const submit = () => {
    if (!canSubmit) return;
    if (mode === "link" && detected && detected.kind !== "invalid") {
      const finalTitle = (title ?? detected.title).trim() || detected.title;
      void run(() =>
        detected.kind === "object"
          ? onAddObject({ ...detected.object, title: finalTitle })
          : onAddLink({ target: detected.target, title: finalTitle, note: "" }),
      );
    } else if (mode === "markdown" && filePath) {
      void run(() => onAddFile(filePath, null));
    } else if (mode === "upload" && upload && uploadPath) {
      void run(async () => {
        if (upload.size > UPLOAD_MAX_BYTES) {
          throw new Error(
            "The file is over 1 MB. Trim it, or link to it instead.",
          );
        }
        const text = await upload.text();
        await onAddFile(uploadPath, newFileContent(upload.name, text));
      });
    }
  };

  return (
    <Dialog open onOpenChange={(open) => !open && !busy && onClose()}>
      <DialogContent className="w-[640px] max-w-[92vw]">
        <DialogHeader>
          <DialogTitle>{TITLES[mode]}</DialogTitle>
          <DialogDescription>
            Agents working in this space read everything here.
          </DialogDescription>
        </DialogHeader>
        <DialogBody>
          {mode === "link" ? (
            <form
              className="flex flex-col gap-3"
              onSubmit={(event) => {
                event.preventDefault();
                submit();
              }}
            >
              <Input
                autoFocus
                aria-label="URL"
                value={url}
                onChange={(event) => {
                  setUrl(event.target.value);
                  setTitle(null);
                }}
                placeholder="https://"
                spellCheck={false}
              />
              <Detection
                detected={detected}
                empty={url.trim().length === 0}
                onConnect={(state) =>
                  state.needsCredentials
                    ? void navigate({ to: "/mcp-servers" })
                    : sources.connect(state)
                }
              />
              {detected && detected.kind !== "invalid" ? (
                <Field label="Title">
                  <Input
                    value={title ?? detected.title}
                    onChange={(event) => setTitle(event.target.value)}
                    placeholder={detected.title}
                  />
                </Field>
              ) : null}
            </form>
          ) : mode === "markdown" ? (
            <form
              className="flex flex-col gap-3"
              onSubmit={(event) => {
                event.preventDefault();
                submit();
              }}
            >
              <Field label="File name">
                <Input
                  autoFocus
                  value={fileName}
                  onChange={(event) => setFileName(event.target.value)}
                  placeholder="pricing.md"
                  spellCheck={false}
                  aria-invalid={fileExists || undefined}
                />
              </Field>
              <Text size="xxs" variant="muted">
                {fileExists
                  ? "There is already a file with this name. Pick another one."
                  : filePath
                    ? `Saved as ${fileDisplayName(filePath)} beside CONTEXT.md. You write it next.`
                    : "Saved beside CONTEXT.md. You write it next."}
              </Text>
            </form>
          ) : (
            <DropZone
              file={upload}
              exists={uploadExists}
              onFile={(file) => {
                setError(
                  isUploadableFile(file)
                    ? null
                    : "Only Markdown and text files for now. Link to anything else.",
                );
                setUpload(isUploadableFile(file) ? file : null);
              }}
              onClear={() => setUpload(null)}
            />
          )}
        </DialogBody>
        <DialogFooter className="items-center sm:justify-between">
          <div className="min-w-0 flex-1">
            {error ? (
              <Text size="xs" className="text-warning-foreground">
                {error}
              </Text>
            ) : null}
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={onClose}
              disabled={busy}
            >
              Cancel
            </Button>
            <Button
              variant="primary"
              size="sm"
              onClick={submit}
              disabled={!canSubmit}
              loading={busy}
            >
              {SUBMIT_LABELS[mode]}
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

type DetectedLink =
  | { kind: "object"; object: ContextObject; title: string }
  | {
      kind: "source";
      source: ContextSource;
      target: string;
      title: string;
      label: string;
      state: ContextSourceState | null;
    }
  | { kind: "web"; target: string; title: string; host: string }
  | { kind: "invalid" };

/**
 * What a pasted URL is: a PostHog object, an item from a source we know how
 * to read through its MCP server, or a web page we keep as a plain link.
 */
function detectLink(
  input: string,
  sources: ContextSources,
): DetectedLink | null {
  const value = input.trim();
  if (!value) return null;
  const object = parsePostHogObjectUrl(value);
  if (object) {
    const label = CONTEXT_OBJECT_KIND_LABELS[object.kind];
    return {
      kind: "object",
      object: { kind: object.kind, url: value, title: `${label} ${object.id}` },
      title: `${label} ${object.id}`,
    };
  }
  const item = parseContextSourceInput(value, null);
  if (item) {
    return {
      kind: "source",
      source: item.source,
      target: item.item.target,
      title: item.item.title,
      label: item.item.label,
      state: sources.byId(item.source.id) ?? null,
    };
  }
  if (isHttpUrl(value)) {
    return {
      kind: "web",
      target: value,
      title: titleFromUrl(value),
      host: hostOf(value),
    };
  }
  return { kind: "invalid" };
}

function titleFromUrl(target: string): string {
  try {
    const url = new URL(target);
    const last = url.pathname.split("/").filter(Boolean).pop();
    return last
      ? decodeURIComponent(last).replace(/[-_]+/g, " ")
      : hostOf(target);
  } catch {
    return target;
  }
}

function hostOf(target: string): string {
  try {
    return new URL(target).host.replace(/^www\./, "");
  } catch {
    return target;
  }
}

/** The line under the URL field: what we made of the link, and whether agents can read it. */
function Detection({
  detected,
  empty,
  onConnect,
}: {
  detected: DetectedLink | null;
  empty: boolean;
  onConnect: (state: ContextSourceState) => void;
}) {
  if (empty || detected === null) {
    return (
      <Text size="xs" variant="muted">
        A Slack channel, Notion page, Linear project, GitHub repo, PostHog
        insight or flag, or any web page.
      </Text>
    );
  }
  if (detected.kind === "invalid") {
    return (
      <Text size="xxs" className="text-warning-foreground">
        Enter a full URL, starting with https://
      </Text>
    );
  }
  if (detected.kind === "object") {
    return (
      <DetectionCard
        icon={KIND_ICONS[detected.object.kind]}
        title={CONTEXT_OBJECT_KIND_LABELS[detected.object.kind]}
        meta="Agents read its live state and what changed."
        status="ok"
      />
    );
  }
  if (detected.kind === "source") {
    const state = detected.state;
    if (!state) {
      return (
        <DetectionCard
          icon={<SourceLogo source={detected.source} />}
          title={`${detected.source.name} · ${detected.label}`}
          meta="No server for this source is available here, so it is saved as a link."
          status="none"
        />
      );
    }
    const connected = state.status === "connected";
    return (
      <DetectionCard
        icon={<SourceLogo source={state.source} />}
        title={`${state.source.name} · ${detected.label}`}
        meta={
          connected
            ? `${state.source.name} is connected. Agents can read this.`
            : unconnectedWarning(state)
        }
        status={connected ? "ok" : "warning"}
        action={
          connected ? null : (
            <Button
              variant="outline"
              size="xs"
              disabled={state.connecting}
              onClick={() => onConnect(state)}
            >
              {state.connecting ? "Waiting" : connectLabel(state)}
            </Button>
          )
        }
      />
    );
  }
  return (
    <DetectionCard
      icon={<LinkIcon size={16} />}
      title={detected.host}
      meta="Saved as a link. Agents open it when they can reach the page."
      status="none"
    />
  );
}

function DetectionCard({
  icon,
  title,
  meta,
  status,
  action,
}: {
  icon: ReactNode;
  title: string;
  meta: string;
  status: "ok" | "warning" | "none";
  action?: ReactNode;
}) {
  return (
    <div className="flex items-center gap-3 rounded-md border border-border px-3 py-2.5">
      <span className="flex size-5 shrink-0 items-center justify-center text-muted-foreground">
        {icon}
      </span>
      <span className="flex min-w-0 flex-1 flex-col gap-0.5">
        <span className="flex items-center gap-1.5 truncate font-medium text-foreground text-xs">
          {title}
          {status === "ok" ? (
            <CheckCircleIcon
              size={13}
              weight="fill"
              className="text-success-foreground"
            />
          ) : status === "warning" ? (
            <WarningCircleIcon
              size={13}
              weight="fill"
              className="text-warning-foreground"
            />
          ) : null}
        </span>
        <span
          className={cn(
            "text-xxs",
            status === "warning"
              ? "text-warning-foreground"
              : "text-muted-foreground",
          )}
        >
          {meta}
        </span>
      </span>
      {action ? <span className="shrink-0">{action}</span> : null}
    </div>
  );
}

function DropZone({
  file,
  exists,
  onFile,
  onClear,
}: {
  file: File | null;
  exists: boolean;
  onFile: (file: File) => void;
  onClear: () => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);

  return (
    <div className="flex flex-col gap-2">
      {/* biome-ignore lint/a11y/noStaticElementInteractions: the drop target is a passive surface; the button inside carries the keyboard path. */}
      <div
        className={cn(
          "flex flex-col items-center gap-3 rounded-md border border-border border-dashed px-6 py-8 text-center transition-colors",
          over && "border-foreground/40 bg-fill-hover",
        )}
        onDragOver={(event) => {
          event.preventDefault();
          setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={(event) => {
          event.preventDefault();
          setOver(false);
          const dropped = event.dataTransfer.files[0];
          if (dropped) onFile(dropped);
        }}
      >
        <span className="flex size-9 items-center justify-center rounded-md border border-border text-muted-foreground">
          {file ? <FileTextIcon size={18} /> : <UploadSimpleIcon size={18} />}
        </span>
        {file ? (
          <div className="flex flex-col gap-0.5">
            <Text size="xs" weight="medium" className="font-mono">
              {file.name}
            </Text>
            <Text
              size="xxs"
              className={exists ? "text-warning-foreground" : undefined}
              variant={exists ? undefined : "muted"}
            >
              {exists
                ? "There is already a file with this name. Rename it first."
                : `${formatBytes(file.size)} · Saved beside CONTEXT.md`}
            </Text>
          </div>
        ) : (
          <div className="flex flex-col gap-0.5">
            <Text size="xs" weight="medium">
              Drop a file here
            </Text>
            <Text size="xxs" variant="muted">
              Markdown or text, up to 1 MB
            </Text>
          </div>
        )}
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => inputRef.current?.click()}
          >
            {file ? "Choose another…" : "Choose a file…"}
          </Button>
          {file ? (
            <Button variant="default" size="sm" onClick={onClear}>
              Remove
            </Button>
          ) : null}
        </div>
        <input
          ref={inputRef}
          type="file"
          accept={UPLOAD_ACCEPT}
          className="hidden"
          onChange={(event) => {
            const picked = event.target.files?.[0];
            if (picked) onFile(picked);
            event.target.value = "";
          }}
        />
      </div>
    </div>
  );
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  const id = useId();
  return (
    <div className="flex flex-col gap-1.5">
      <label
        htmlFor={id}
        className="font-medium text-muted-foreground text-xxs"
      >
        {label}
      </label>
      <div className="[&_input]:w-full">{children}</div>
    </div>
  );
}
