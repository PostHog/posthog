import type React from "react";

const PATHS: Record<string, React.JSX.Element> = {
  select: <path d="M4 2.5l8 7-3.6.7 2 3.6-2 1-2-3.7-2.4 2.6z" />,
  crop: (
    <>
      <path d="M4.5 1.5v10h10" />
      <path d="M1.5 4.5h10v10" />
    </>
  ),
  counter: (
    <>
      <circle cx="8" cy="8" r="5.8" />
      <path d="M6.8 6.2L8.3 5.2v5.6" />
    </>
  ),
  "text-bg": (
    <>
      <rect x="2" y="2.5" width="12" height="11" rx="2.5" />
      <path d="M5.5 6V5h5v1M8 5v6M6.8 11h2.4" />
    </>
  ),
  trash: (
    <>
      <path d="M3 4.5h10" />
      <path d="M6.5 4.5V3h3v1.5" />
      <path d="M4.5 4.5l.7 8a1 1 0 0 0 1 .9h3.6a1 1 0 0 0 1-.9l.7-8" />
      <path d="M6.7 7v4M9.3 7v4" />
    </>
  ),
  arrow: (
    <>
      <path d="M3.5 12.5L12 4" />
      <path d="M6.5 4H12v5.5" />
    </>
  ),
  rect: <rect x="2.5" y="3.5" width="11" height="9" rx="1.5" />,
  ellipse: <ellipse cx="8" cy="8" rx="5.5" ry="4.5" />,
  pen: <path d="M2.5 13.5c3.5.5 3-6 5.5-6s1.5 5 3 5 1.5-2.5 2.5-4.5" />,
  text: (
    <>
      <path d="M3.5 4.5V3h9v1.5" />
      <path d="M8 3v10" />
      <path d="M6 13h4" />
    </>
  ),
  pixelate: (
    <>
      <path d="M3 3h3v3H3zM9 3h3v3H9zM6 6h3v3H6zM3 9h3v3H3zM9 9h3v3H9z" />
    </>
  ),
  undo: (
    <>
      <path d="M5.5 3.5L2.5 6.5l3 3" />
      <path d="M2.5 6.5H10a3.5 3.5 0 0 1 0 7H7" />
    </>
  ),
  redo: (
    <>
      <path d="M10.5 3.5l3 3-3 3" />
      <path d="M13.5 6.5H6a3.5 3.5 0 0 0 0 7h3" />
    </>
  ),
};

export function ToolIcon({ tool }: { tool: string }): React.JSX.Element {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.4"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {PATHS[tool]}
    </svg>
  );
}
