import { type ChainedCommands, Extension, InputRule } from "@tiptap/core";

type BlockStarter = (chain: ChainedCommands, match: RegExpMatchArray) => void;

/**
 * Shift+Enter inserts a hard break rather than a new paragraph, so every line
 * after the first shares one textblock. StarterKit's list and code-block input
 * rules only match at the start of a textblock, which leaves `* ` inert on any
 * line but the first. These fire at a hard break instead, dropping the break so
 * the new block starts on its own line.
 */
function startBlockAfterHardBreak(find: RegExp, run: BlockStarter): InputRule {
  return new InputRule({
    find,
    handler: ({ state, range, match, chain }) => {
      const $start = state.doc.resolve(range.from);
      if ($start.nodeBefore?.type.name !== "hardBreak") return null;
      run(
        chain()
          .deleteRange({ from: range.from - 1, to: range.to })
          .splitBlock(),
        match,
      );
      return undefined;
    },
  });
}

/**
 * The `code` mark's own rule needs the opening backtick to follow whitespace or
 * a block start; a hard break is neither, so `x` at the head of a wrapped line
 * stays literal without this.
 */
function inlineCodeAfterHardBreak(): InputRule {
  return new InputRule({
    find: /`(?!\s)([^`]+)`$/,
    handler: ({ state, range, match, chain }) => {
      const $start = state.doc.resolve(range.from);
      if ($start.nodeBefore?.type.name !== "hardBreak") return null;
      chain()
        .deleteRange(range)
        .insertContent({
          type: "text",
          text: match[1],
          marks: [{ type: "code" }],
        })
        .unsetMark("code")
        .run();
      return undefined;
    },
  });
}

export const MarkdownLineStartRules = Extension.create({
  name: "markdownLineStartRules",

  addInputRules() {
    return [
      startBlockAfterHardBreak(/([-+*])\s$/, (chain) =>
        chain.toggleBulletList().run(),
      ),
      startBlockAfterHardBreak(/(\d+)[.)]\s$/, (chain, match) => {
        chain
          .toggleOrderedList()
          .updateAttributes("orderedList", {
            start: Number.parseInt(match[1], 10) || 1,
          })
          .run();
      }),
      startBlockAfterHardBreak(/```([a-zA-Z0-9+#-]*)\s$/, (chain, match) => {
        const language = match[1];
        chain.setCodeBlock(language ? { language } : undefined).run();
      }),
      inlineCodeAfterHardBreak(),
    ];
  },
});
