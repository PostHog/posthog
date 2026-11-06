import { SpaceSelect } from "@posthog/ui/features/canvas/components/SpaceSelect";

export function NewSessionHeading({
  channelId,
  onChangeSpace,
  disabled = false,
}: {
  channelId: string | null;
  onChangeSpace: (channelId: string) => void;
  disabled?: boolean;
}) {
  return (
    <div className="mb-5 flex flex-col font-semibold text-[26px] leading-tight tracking-tight">
      <span>Start a new session</span>
      <span className="flex min-w-0 flex-wrap items-baseline gap-x-2 text-muted-foreground">
        in
        <SpaceSelect
          variant="headline"
          value={channelId ?? ""}
          onChange={onChangeSpace}
          disabled={disabled}
        />
        {channelId ? "space" : null}
      </span>
    </div>
  );
}
