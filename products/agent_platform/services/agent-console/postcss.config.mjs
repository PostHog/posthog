/**
 * Tailwind v4 via PostCSS — same pattern Next.js v15 uses.
 * Vite (Storybook) uses `@tailwindcss/vite` instead; see `.storybook/main.ts`.
 */
const config = {
    plugins: {
        '@tailwindcss/postcss': {},
    },
}

export default config
