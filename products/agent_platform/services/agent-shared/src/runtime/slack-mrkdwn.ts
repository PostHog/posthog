/** Convert the Markdown an LLM emits into Slack mrkdwn: `*bold*` (not `**`),
 *  `_italic_`, `<url|text>` links, `•` bullets, no headings/rules. Code spans
 *  and `>` quotes are already Slack-compatible and left untouched. */
export function markdownToMrkdwn(input: string): string {
    // Shield code (already Slack-compatible) behind placeholder tokens so the
    // rewrites below can't mangle its contents; restored at the end.
    const fences: string[] = []
    const inline: string[] = []
    let text = input
        .replace(/```[\s\S]*?```/g, (m) => `@@CODEFENCE${fences.push(m) - 1}@@`)
        .replace(/`[^`\n]+`/g, (m) => `@@CODESPAN${inline.push(m) - 1}@@`)

    text = text
        .replace(/^[ \t]*#{1,6}[ \t]+(.+?)[ \t]*$/gm, (_m, h: string) => `@@BOLD@@${h.replace(/\*/g, '')}@@BOLD@@`) // headings -> bold (no nested emphasis)
        .replace(/^[ \t]*([-*_])\1{2,}[ \t]*$/gm, '──────────') // horizontal rules -> divider
        .replace(/^([ \t]*)[-*+] \[[ ]\][ \t]+/gm, '$1• ☐ ') // unchecked task -> bullet
        .replace(/^([ \t]*)[-*+] \[[xX]\][ \t]+/gm, '$1• ☑ ') // checked task -> bullet
        .replace(/^([ \t]*)[-*+][ \t]+/gm, '$1• ') // list markers -> bullets
        .replace(/!\[[^\]]*\]\(\s*([^)\s]+)(?:\s+"[^"]*")?\s*\)/g, '<$1>') // images -> <url>
        .replace(/\[([^\]]+)\]\(\s*([^)\s]+)(?:\s+"[^"]*")?\s*\)/g, '<$2|$1>') // [text](url "title") -> <url|text>
        .replace(/\*\*\*(.+?)\*\*\*/g, '@@BOLD@@_$1_@@BOLD@@') // bold+italic -> *_x_*
        .replace(/\*\*(.+?)\*\*/g, '@@BOLD@@$1@@BOLD@@') // bold ** -> token
        .replace(/__(.+?)__/g, '@@BOLD@@$1@@BOLD@@') // bold __ -> token
        .replace(/~~(.+?)~~/g, '~$1~') // strikethrough ~~x~~ -> ~x~
        .replace(/\*([^*\n]+)\*/g, '_$1_') // italic * -> _ (leave _italic_ as-is)
        .replace(/@@BOLD@@/g, '*') // tokens -> single * (after italics)

    return text
        .replace(/@@CODESPAN(\d+)@@/g, (_m, i) => inline[Number(i)])
        .replace(/@@CODEFENCE(\d+)@@/g, (_m, i) => fences[Number(i)])
}
