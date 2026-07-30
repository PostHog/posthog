// Trunk's merge queue tests each batch on a `trunk-merge/**` branch whose diff
// against master also carries every PR stacked underneath (optimistic parallel
// mode), so filters fed that diff run far more jobs than the batch's own
// changes require. The queue PR body authored by Trunk declares which PRs the
// branch actually tests; parsing it lets filters scope to those PRs' files.
// Callers MUST treat an empty result as "fall back to the full branch diff",
// never as "nothing changed".

const TESTED_HEADING = /^##\s+Pull Requests Being Tested\s*$/im
const NEXT_HEADING = /^##\s/m
// Queue branches are named `trunk-merge/pr-<lead>/<uuid>` (bisection runs add a
// suffix after the uuid). The lead PR is always in the tested set, so callers
// use it to cross-check the body parse.
const TRUNK_MERGE_REF = /^trunk-merge\/pr-(\d+)\//

export function trunkMergeLeadPr(ref: string | undefined): number | null {
  const match = ref?.match(TRUNK_MERGE_REF)
  return match ? parseInt(match[1], 10) : null
}

export function parseTestedPrNumbers(body: string | null | undefined, repo: {owner: string; repo: string}): number[] {
  if (!body) {
    return []
  }
  const heading = body.match(TESTED_HEADING)
  if (!heading || heading.index === undefined) {
    return []
  }
  const rest = body.slice(heading.index + heading[0].length)
  const nextHeading = rest.search(NEXT_HEADING)
  const section = nextHeading === -1 ? rest : rest.slice(0, nextHeading)
  // Only same-repo PR links on the real github.com host count: a foreign
  // number would make the caller fetch an unrelated PR's files and silently
  // under-select jobs.
  const prLink = new RegExp(
    `//(?:www\\.)?github\\.com/${escapeRegExp(repo.owner)}/${escapeRegExp(repo.repo)}/pull/(\\d+)`,
    'gi'
  )
  const numbers = new Set<number>()
  for (const match of section.matchAll(prLink)) {
    numbers.add(parseInt(match[1], 10))
  }
  return [...numbers]
}

function escapeRegExp(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}
