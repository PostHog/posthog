// Scopes postcss config to the quill workspace so vite builds don't walk up
// and pick up the repo-root config (which targets webpack/Storybook v7 and
// pulls in autoprefixer/cssnano deps that aren't part of the quill graph).
// Quill uses Tailwind v4 via @tailwindcss/vite, no extra postcss plugins needed.
module.exports = { plugins: [] }
