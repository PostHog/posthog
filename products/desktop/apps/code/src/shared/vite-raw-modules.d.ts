// Type declarations for Vite-style raw imports (e.g. `import txt from "./file.txt?raw"`).
// These are not valid module names for classic TS resolution, but Vite supports them.

declare module "*.html?raw" {
  const content: string;
  export default content;
}
