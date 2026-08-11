import { xmlToContent } from "@posthog/core/message-editor/content";
import { type GithubRefKind, parseGithubIssueUrl } from "@/lib/githubIssueUrl";

/**
 * A run of message text split around the composer's pseudo-tags — the
 * `<file path="…" />` / `<github_pr number="…" title="…" url="…" />` markup the
 * desktop composer serializes chips into. Mobile receives that raw markup in
 * task descriptions, chat messages and report bodies, so it has to render the
 * tags as chips rather than as angle-bracket noise.
 */
export type PseudoTagSegment =
  | { type: "text"; text: string }
  | { type: "file"; path: string; label: string; fromDesktop: boolean }
  | { type: "github"; kind: GithubRefKind; url: string; label: string };

/**
 * Paths that only exist on the machine the desktop app ran on. Phones can't
 * open these, so the chip says where they came from instead of pretending the
 * file is reachable.
 */
const DESKTOP_LOCAL_PATH_PATTERN =
  /^(?:\/(?:var|private|Users|home|tmp|opt)(?:\/|$)|~\/|[A-Za-z]:[\\/])/;

export function isDesktopLocalPath(path: string): boolean {
  return DESKTOP_LOCAL_PATH_PATTERN.test(path);
}

/**
 * Splits `text` into renderable segments using the same grammar the desktop
 * composer emits with — `xmlToContent` from `@posthog/core` is the single
 * source of truth for that grammar, so mobile can't drift from it.
 *
 * Tags the parser doesn't recognise (malformed, unclosed, unknown) stay in the
 * text segments verbatim, which is the safe fallback: worst case the user sees
 * what they see today.
 */
export function parsePseudoTags(text: string): PseudoTagSegment[] {
  const segments: PseudoTagSegment[] = [];

  const pushText = (value: string) => {
    if (!value) return;
    const last = segments[segments.length - 1];
    // Keep adjacent text contiguous so markdown spanning a dropped tag (e.g.
    // `**bold <error id="x" /> bold**`) still parses as one run.
    if (last?.type === "text") last.text += value;
    else segments.push({ type: "text", text: value });
  };

  for (const segment of xmlToContent(text).segments) {
    if (segment.type === "text") {
      pushText(segment.text);
      continue;
    }

    const chip = segment.chip;
    switch (chip.type) {
      case "file":
      case "folder":
        segments.push({
          type: "file",
          path: chip.id,
          label: chip.label,
          fromDesktop: isDesktopLocalPath(chip.id),
        });
        break;
      case "github_pr":
      case "github_issue": {
        const ref = parseGithubIssueUrl(chip.id);
        // A tag whose url isn't a canonical GitHub ref gets its label as plain
        // text rather than a chip that would open somewhere unexpected.
        if (!ref) pushText(chip.label);
        else
          segments.push({
            type: "github",
            kind: ref.kind,
            url: ref.normalizedUrl,
            label: chip.label,
          });
        break;
      }
      case "command":
        pushText(`/${chip.label}`);
        break;
      default:
        // error / experiment / insight / feature_flag have no mobile surface to
        // link to; desktop renders them as `@label`, so match that.
        pushText(`@${chip.label}`);
        break;
    }
  }

  return segments;
}
