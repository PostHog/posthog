import { Spinner } from "@posthog/ui/primitives/Spinner";

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
        <Spinner size="md" />
        <span>{loadingMessage}</span>
      </span>
    );
  }
  return <span className={className}>{emptyMessage}</span>;
}
