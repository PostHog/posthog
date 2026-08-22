import { ArrowSquareOut, Star } from "@phosphor-icons/react";
import {
  type LeanSkill,
  leanSkillRepoUrl,
} from "@posthog/core/billing/leanSkills";
import {
  Button,
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Text,
} from "@posthog/quill";
import { LeanSkillMark } from "@posthog/ui/features/cost-management/LeanSkillMark";
import { useRepoStars } from "@posthog/ui/features/cost-management/useRepoStars";

interface LeanSkillDialogProps {
  skill: LeanSkill;
  installed: boolean;
  busy: boolean;
  onInstall: () => void;
  onUninstall: () => void;
  onClose: () => void;
}

/**
 * One skill: what it does, what was measured, and where to read the rest. The
 * repository link carries everything this does not, so the dialog stays a
 * recap rather than a transcription.
 */
export function LeanSkillDialog({
  skill,
  installed,
  busy,
  onInstall,
  onUninstall,
  onClose,
}: LeanSkillDialogProps) {
  const stars = useRepoStars(skill.source);

  return (
    <Dialog
      open
      onOpenChange={(next) => {
        if (!next) onClose();
      }}
    >
      <DialogContent className="max-w-[440px]">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <LeanSkillMark size={18} />
            {skill.name}
            <Text size="xxs" variant="muted" render={<span />}>
              {skill.license}
            </Text>
          </DialogTitle>
          <DialogDescription>{skill.summary}</DialogDescription>
        </DialogHeader>

        <DialogBody>
          <div className="flex flex-col gap-4">
            <Section label="How it works" body={skill.mechanism} />
            <Section
              label="Measured"
              body={
                skill.evidence
                  ? `${skill.evidence} - ${skill.evidenceSource}`
                  : "Nobody has measured this one."
              }
              note={skill.caveat}
            />
            <div className="flex flex-wrap items-center gap-4">
              <span className="inline-flex items-center gap-2">
                <SkillLink href={leanSkillRepoUrl(skill)}>Repository</SkillLink>
                {stars !== null && <RepoStars count={stars} />}
              </span>
              {skill.evidenceUrl && (
                <SkillLink href={skill.evidenceUrl}>
                  {`${skill.evidenceSource} trial`}
                </SkillLink>
              )}
            </div>
          </div>
        </DialogBody>

        <DialogFooter>
          <Button variant="outline" size="sm" onClick={onClose}>
            Close
          </Button>
          <Button
            variant={installed ? "outline" : "primary"}
            size="sm"
            loading={busy}
            disabled={busy}
            data-attr={`cost-management-${installed ? "uninstall" : "install"}-${skill.id}`}
            onClick={installed ? onUninstall : onInstall}
          >
            {installed ? "Uninstall" : "Install"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function RepoStars({ count }: { count: number }) {
  return (
    <Text
      size="xxs"
      variant="muted"
      render={<span />}
      className="inline-flex items-center gap-1"
    >
      <Star size={11} weight="fill" aria-hidden="true" />
      {starFormat.format(count).toLowerCase()}
    </Text>
  );
}

const starFormat = new Intl.NumberFormat("en", {
  notation: "compact",
  maximumFractionDigits: 1,
});

function Section({
  label,
  body,
  note,
}: {
  label: string;
  body: string;
  note?: string;
}) {
  return (
    <div className="flex flex-col gap-1">
      <Text
        size="xxs"
        weight="medium"
        variant="muted"
        className="uppercase tracking-wide"
      >
        {label}
      </Text>
      <Text size="xs">{body}</Text>
      {note && (
        <Text size="xs" variant="muted">
          {note}
        </Text>
      )}
    </div>
  );
}

function SkillLink({ href, children }: { href: string; children: string }) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      className="inline-flex items-center gap-1 text-xs underline decoration-(--gray-7)"
    >
      {children}
      <ArrowSquareOut size={11} aria-hidden="true" />
    </a>
  );
}
