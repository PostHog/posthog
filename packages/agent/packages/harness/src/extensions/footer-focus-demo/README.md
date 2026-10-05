# footer-focus-demo

POC extension demonstrating TUI focus/overlay patterns, not a real harness
capability. **Not** registered in [`registry.ts`](../registry.ts) — the real
thing (subagent status footer + overlay, see `../subagent/status-*.ts`) now
owns `ctx.ui.setFooter()`/`setEditorComponent()` for real, and only one
extension can own those at a time. Run this one standalone instead:

```bash
pi -e packages/harness/src/extensions/footer-focus-demo/index.ts
```

(or build the package first and point `-e` at the compiled
`dist/extensions/footer-focus-demo/index.js`.) See "Trying it" below.

## Trying it

```bash
cd packages/harness
pnpm exec pi -e src/extensions/footer-focus-demo/index.ts
```

Then, in the interactive session:

1. Make sure the editor is empty, then press **Down**. Focus moves into the
   footer; the first item ("Welcome notification") highlights.
2. Press **Down**/**Up** to move between the two seeded items.
3. Press **Enter** on a highlighted item to open the overlay with its detail
   text. **Enter**/**Esc** closes the overlay.
4. Press **Esc**, or **Up** while the first item is highlighted, to hand
   focus back to the editor — you can type normally again.
5. Run `/footer-demo:add some text` to add more items, or
   `/footer-demo:clear` to empty the list and confirm Down is then a no-op
   (normal editor behavior, no footer focus).

## What it shows

- **Pattern 6 (Custom Footer)** + **Pattern 4 (Persistent Status Indicator)**:
  [`footer.ts`](./footer.ts) renders a list of items in the footer via
  `ctx.ui.setFooter()`, highlighting whichever one is focused.
- **Keyboard focus into the footer**: [`editor.ts`](./editor.ts) wraps
  `CustomEditor` (**Pattern 7**) so that pressing Down with an empty editor
  moves focus into the footer *if an item is present* — the hand-off is a
  no-op otherwise. Up/Down then move between footer items; Esc, or Up from
  the first item, returns focus to the editor.
- **Overlays**: [`overlay.ts`](./overlay.ts) opens an overlay with
  `ctx.ui.custom({ overlay: true })` when Enter is pressed on a focused item.

State lives in [`inbox.ts`](./inbox.ts) (`FooterInbox`), deliberately free of
any pi/TUI imports so it's plain and easy to unit test.

Two demo items are seeded on `session_start`. `/footer-demo:add [text]` and
`/footer-demo:clear` let you add/remove items at runtime to see the
"IF an item is present" behavior — with an empty list, Down in the editor
behaves exactly as it does by default.
