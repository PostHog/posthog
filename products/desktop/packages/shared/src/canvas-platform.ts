// The canvas platform contract, vendored from the PostHog repo's single source
// of truth: products/canvas/packages/canvas_builder/manifest.json. The server
// builds and validates against that file; this copy exists so the client's
// legacy import map (freeformWhitelist) is contract-tested against the same
// pins. When the server manifest changes, update this constant to match.
export const CANVAS_PLATFORM_MANIFEST = {
  canvasSdkVersion: "0.1.0",
  dependencies: {
    react: {
      version: "19.0.0",
      url: "https://esm.sh/react@19.0.0",
    },
    "react-dom": {
      version: "19.0.0",
      url: "https://esm.sh/react-dom@19.0.0?external=react",
    },
    "@posthog/quill": {
      version: "0.3.0-beta.18",
      url: "https://esm.sh/@posthog/quill@0.3.0-beta.18?external=react,react-dom",
    },
    recharts: {
      version: "2.15.0",
      url: "https://esm.sh/recharts@2.15.0?external=react,react-dom",
    },
    "lucide-react": {
      version: "1.21.0",
      url: "https://esm.sh/lucide-react@1.21.0?external=react",
    },
    dayjs: {
      version: "1.11.13",
      url: "https://esm.sh/dayjs@1.11.13",
    },
    d3: { version: "7.9.0", url: "https://esm.sh/d3@7.9.0" },
    three: { version: "0.179.1", url: "https://esm.sh/three@0.179.1" },
    "framer-motion": {
      version: "12.23.12",
      url: "https://esm.sh/framer-motion@12.23.12?external=react,react-dom",
    },
    zod: { version: "3.25.76", url: "https://esm.sh/zod@3.25.76" },
    "@tanstack/react-table": {
      version: "8.21.3",
      url: "https://esm.sh/@tanstack/react-table@8.21.3?external=react,react-dom",
    },
    "@tanstack/react-virtual": {
      version: "3.14.9",
      url: "https://esm.sh/@tanstack/react-virtual@3.14.9?external=react,react-dom",
    },
    "react-hook-form": {
      version: "7.85.0",
      url: "https://esm.sh/react-hook-form@7.85.0?external=react",
    },
    "lodash-es": {
      version: "4.18.1",
      url: "https://esm.sh/lodash-es@4.18.1",
    },
    "react-markdown": {
      version: "10.1.0",
      url: "https://esm.sh/react-markdown@10.1.0?external=react",
    },
    papaparse: {
      version: "5.6.0",
      url: "https://esm.sh/papaparse@5.6.0",
    },
  },
  runtimeImports: {
    "react/jsx-runtime": "https://esm.sh/react@19.0.0/jsx-runtime",
    "react-dom/client": "https://esm.sh/react-dom@19.0.0/client?external=react",
  },
  allowedImportSpecifiers: [
    "react",
    "react-dom",
    "react-dom/client",
    "@posthog/quill",
    "recharts",
    "lucide-react",
    "dayjs",
    "d3",
    "three",
    "framer-motion",
    "zod",
    "@tanstack/react-table",
    "@tanstack/react-virtual",
    "react-hook-form",
    "lodash-es",
    "react-markdown",
    "papaparse",
  ],
  csp: "default-src 'none'; base-uri 'none'; object-src 'none'; form-action 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'none'; img-src 'self' data: blob:; font-src 'self' data:; media-src 'self' data: blob:; worker-src 'self' blob:",
  limits: {
    maxSourceFiles: 64,
    maxSourceFileBytes: 524288,
    maxSourceTotalBytes: 2097152,
    maxArtifactFiles: 256,
    maxArtifactFileBytes: 4194304,
    maxArtifactTotalBytes: 12582912,
  },
} as const;
