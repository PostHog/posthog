import { Spinner } from "@posthog/quill";

interface SuggestionStatusProps {
  loading: boolean;
  emptyMessage: string;
  loadingMessage?: string;
  className?: string;
}

export function SuggestionStatus({
  loading,
  emptyMessage,
  loadingMessage = "Loading...",
  className = "flex items-center gap-2 text-[var(--gray-11)]",
}: SuggestionStatusProps) {
  if (loading) {
    return (
      <span className={className}>
        <Spinner className="h-3.5 w-3.5" />
        <span>{loadingMessage}</span>
      </span>
    );
  }
  return <span className={className}>{emptyMessage}</span>;
}
