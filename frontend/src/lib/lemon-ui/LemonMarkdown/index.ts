export { LemonMarkdown, type LemonMarkdownProps, slugifyHeading } from './LemonMarkdown'
// LemonMarkdownWithMermaid is deliberately not re-exported: this barrel is imported by lib
// components shipped in the toolbar bundle, and the mermaid variant must stay out of that graph.
// Import it from 'lib/lemon-ui/LemonMarkdown/LemonMarkdownWithMermaid' directly.
