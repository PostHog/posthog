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
 * One skill, with one thing to look at first: the figure a trial measured,
 * inside a quote that names the trial. Everything under it is smaller on
 * purpose, so the card has a reading order instead of five equal blocks.
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
      <DialogContent className="max-w-[520px]">
        <DialogHeader>
          <DialogTitle>{skill.name}</DialogTitle>
          <DialogDescription>{skill.summary}</DialogDescription>
        </DialogHeader>

        <DialogBody>
          <div className="flex flex-col gap-5">
            {skill.trial && <TrialQuote trial={skill.trial} />}

            <Block label="How it goes about it">
              <Text size="xs" variant="muted">
                {skill.approach}
              </Text>
            </Block>

            {skill.example && (
              <Block label="In practice">
                <div className="flex flex-col gap-2 rounded-(--radius-3) bg-(--gray-2) px-3 py-2.5">
                  <Text size="xxs" variant="muted">
                    {skill.example.ask}
                  </Text>
                  <ExampleRow label="without" body={skill.example.without} />
                  <ExampleRow label="with" body={skill.example.with} mono />
                </div>
              </Block>
            )}
          </div>
        </DialogBody>

        <DialogFooter>
          <span className="mr-auto flex items-center gap-2 self-center">
            <Text size="xxs" variant="muted" render={<span />}>
              {skill.license}
            </Text>
            <SkillLink href={leanSkillRepoUrl(skill)}>Repository</SkillLink>
            {stars !== null && <RepoStars count={stars} />}
          </span>
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

/** The trial's finding, led by its figure and closed by its name. */
function TrialQuote({ trial }: { trial: NonNullable<LeanSkill["trial"]> }) {
  return (
    <blockquote className="m-0 flex flex-col gap-2 border-(--gray-6) border-l-2 pl-3.5">
      <span className="flex items-baseline gap-2">
        <span className="font-medium text-(--gray-12) text-[26px] tabular-nums leading-none">
          {trial.headline}
        </span>
        <Text size="xs" render={<span />}>
          {trial.headlineLabel}
        </Text>
      </span>
      <Text size="xs" variant="muted">
        {trial.finding}
      </Text>
      <span className="flex flex-wrap items-center gap-x-1.5">
        <Text size="xxs" variant="muted" render={<span />}>
          {`${trial.source} · ${trial.sample} ·`}
        </Text>
        <SkillLink href={trial.url}>Read the trial</SkillLink>
      </span>
    </blockquote>
  );
}

/** A small dark label over quieter content, so the eye has a landmark. */
function Block({ label, children }: { label: string; children: JSX.Element }) {
  return (
    <div className="flex flex-col gap-2">
      <Text size="xxs" weight="medium">
        {label}
      </Text>
      {children}
    </div>
  );
}

/** One side of the project's illustration, labeled so it reads as one. */
function ExampleRow({
  label,
  body,
  mono = false,
}: {
  label: string;
  body: string;
  mono?: boolean;
}) {
  return (
    <span className="flex items-baseline gap-3">
      <Text
        size="xxs"
        variant="muted"
        render={<span />}
        className="w-[46px] shrink-0"
      >
        {label}
      </Text>
      <Text size="xs" render={<span />} className={mono ? "font-mono" : ""}>
        {body}
      </Text>
    </span>
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

function SkillLink({ href, children }: { href: string; children: string }) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      className="inline-flex w-fit items-center gap-1 text-[11px] underline decoration-(--gray-7)"
    >
      {children}
      <ArrowSquareOut size={10} aria-hidden="true" />
    </a>
  );
}
