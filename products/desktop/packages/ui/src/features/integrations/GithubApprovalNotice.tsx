import { CheckCircle, Clock } from "@phosphor-icons/react";
import {
  cn,
  Item,
  ItemContent,
  ItemDescription,
  ItemMedia,
  ItemTitle,
} from "@posthog/quill";

export function GithubApprovalNotice({
  state,
  className,
}: {
  state: "awaiting" | "approved";
  className?: string;
}) {
  if (state === "awaiting") {
    return (
      <Item variant="muted" size="sm" tone="warning" className={className}>
        <ItemMedia variant="icon">
          <Clock size={16} />
        </ItemMedia>
        <ItemContent>
          <ItemTitle>Waiting for a GitHub org owner to approve</ItemTitle>
          <ItemDescription>
            Cloud runs will not be available until your integration is approved.
            In the meantime, you can run tasks on your local machine.
          </ItemDescription>
        </ItemContent>
      </Item>
    );
  }

  return (
    <Item variant="muted" size="sm" tone="success" className={cn(className)}>
      <ItemMedia variant="icon">
        <CheckCircle size={16} weight="fill" />
      </ItemMedia>
      <ItemContent>
        <ItemTitle>Your GitHub org owner approved the request</ItemTitle>
      </ItemContent>
    </Item>
  );
}
