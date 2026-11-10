import { GitlabLogo, MagnifyingGlass } from "@phosphor-icons/react";
import {
  Button,
  Combobox,
  ComboboxContent,
  ComboboxEmpty,
  ComboboxInput,
  ComboboxItem,
  ComboboxList,
  ComboboxTrigger,
  cn,
  InputGroupAddon,
  Text,
} from "@posthog/quill";
import { Spinner } from "@posthog/ui/primitives/Spinner";
import { type RefObject, useRef } from "react";

interface GitLabProjectPickerProps {
  value: string | null;
  onChange: (project: string | null) => void;
  projects: string[];
  isLoading: boolean;
  loadFailed: boolean;
  onRetry: () => void;
  /** Token scopes that coding tasks need and the GitLab token lacks. */
  missingScopes: string[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
  searchQuery: string;
  onSearchQueryChange: (value: string) => void;
  disabled?: boolean;
  anchor?: RefObject<HTMLElement | null>;
}

export function GitLabProjectPicker({
  value,
  onChange,
  projects,
  isLoading,
  loadFailed,
  onRetry,
  missingScopes,
  open,
  onOpenChange,
  searchQuery,
  onSearchQueryChange,
  disabled = false,
  anchor,
}: GitLabProjectPickerProps) {
  const triggerRef = useRef<HTMLButtonElement>(null);

  return (
    <Combobox
      items={projects}
      // The server filters by the search, so the list shows what it returns.
      filter={null}
      value={value}
      onValueChange={(next) => onChange(next ? (next as string) : null)}
      open={open}
      onOpenChange={(nextOpen) => {
        onOpenChange(nextOpen);
        if (!nextOpen) onSearchQueryChange("");
      }}
      inputValue={searchQuery}
      onInputValueChange={onSearchQueryChange}
      disabled={disabled}
    >
      <ComboboxTrigger
        render={
          <Button
            ref={triggerRef}
            variant="outline"
            size="sm"
            disabled={disabled}
            aria-label="GitLab project"
            data-attr="task-input-gitlab-project-picker"
          >
            <GitlabLogo size={14} weight="regular" className="shrink-0" />
            <span className="min-w-0 truncate">
              {value ?? "GitLab project"}
            </span>
          </Button>
        }
      />
      <ComboboxContent
        anchor={anchor ?? triggerRef}
        side="bottom"
        sideOffset={6}
        className="flex h-80 min-w-(--anchor-width) flex-col"
      >
        <ComboboxInput
          placeholder="Search GitLab projects..."
          showTrigger={false}
        >
          <InputGroupAddon align="inline-start">
            <MagnifyingGlass size={14} />
          </InputGroupAddon>
        </ComboboxInput>
        {missingScopes.length > 0 ? (
          <Text
            size="xs"
            variant="muted"
            className="shrink-0 border-b px-3 py-2"
            data-attr="task-input-gitlab-missing-scopes"
          >
            {`Tasks need a GitLab token with the ${missingScopes.join(", ")} ${missingScopes.length === 1 ? "scope" : "scopes"}. Reconnect GitLab with a new token.`}
          </Text>
        ) : null}
        {loadFailed && projects.length > 0 ? (
          <LoadError onRetry={onRetry} className="shrink-0 border-b" />
        ) : null}
        <ComboboxEmpty
          className={cn(
            "h-auto whitespace-normal",
            (isLoading || loadFailed) &&
              "flex-1 flex-col items-center justify-center gap-2",
          )}
        >
          {isLoading ? (
            <>
              <Spinner size="md" aria-hidden="true" />
              <Text size="sm" variant="muted">
                Loading GitLab projects
              </Text>
            </>
          ) : loadFailed ? (
            <LoadError
              onRetry={onRetry}
              className="flex-col px-6 text-center"
            />
          ) : (
            "No GitLab projects found. Each GitLab project needs its own connection."
          )}
        </ComboboxEmpty>
        <ComboboxList className="flex-1">
          {(project: string) => (
            <ComboboxItem key={project} value={project}>
              {project}
            </ComboboxItem>
          )}
        </ComboboxList>
      </ComboboxContent>
    </Combobox>
  );
}

function LoadError({
  onRetry,
  className,
}: {
  onRetry: () => void;
  className: string;
}) {
  return (
    <div
      className={cn("flex items-center gap-2 px-3 py-2", className)}
      data-attr="task-input-gitlab-load-error"
    >
      <Text size="xs" variant="muted">
        Couldn't load GitLab projects. Retry, or reconnect GitLab if this keeps
        happening.
      </Text>
      <Button
        variant="outline"
        size="xs"
        className="shrink-0"
        // Keeps focus in the search field so the popup stays open.
        onMouseDown={(event) => event.preventDefault()}
        onClick={onRetry}
        data-attr="task-input-gitlab-retry"
      >
        Retry
      </Button>
    </div>
  );
}
