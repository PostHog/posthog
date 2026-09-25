"use dom";

import type { DOMProps } from "expo/dom";
import mermaid from "mermaid";
import { useEffect, useId, useRef, useState } from "react";

export default function MermaidDiagram({
  code,
  dark,
}: {
  code: string;
  dark: boolean;
  dom?: DOMProps;
}) {
  const id = useId().replace(/[^a-zA-Z0-9]/g, "");
  const container = useRef<HTMLDivElement>(null);
  const [diagram, setDiagram] = useState<{
    html: string;
    height: number;
  } | null>(null);
  const [failed, setFailed] = useState(false);
  const [showSource, setShowSource] = useState(false);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let active = true;
    setFailed(false);
    setDiagram(null);
    mermaid.initialize({
      startOnLoad: false,
      securityLevel: "strict",
      theme: dark ? "dark" : "default",
      suppressErrorRendering: true,
      maxTextSize: 50_000,
      flowchart: { htmlLabels: false },
      deterministicIds: true,
      secure: [
        "secure",
        "securityLevel",
        "startOnLoad",
        "maxTextSize",
        "suppressErrorRendering",
        "themeCSS",
        "themeVariables",
        "fontFamily",
        "htmlLabels",
        "flowchart",
      ],
    });
    void mermaid
      .render(`diagram${id}${attempt}`, code, container.current ?? undefined)
      .then(({ svg }) => {
        if (!active) return;
        const parsed = new DOMParser().parseFromString(svg, "image/svg+xml");
        const dimensions = parsed.documentElement
          .getAttribute("viewBox")
          ?.split(/\s+/)
          .map(Number);
        const width = container.current?.clientWidth || 300;
        const height =
          dimensions?.[2] && dimensions[3]
            ? Math.min(
                500,
                Math.max(120, (width * dimensions[3]) / dimensions[2]),
              )
            : 240;
        // The diagram cannot run scripts, navigate the app, or load external resources.
        const html = `<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src data:; base-uri 'none'; form-action 'none'"><style>body{margin:0}svg{max-width:100%;height:auto}</style></head><body>${svg}</body></html>`;
        setDiagram({ html, height });
      })
      .catch(() => {
        if (active) setFailed(true);
      });
    return () => {
      active = false;
    };
  }, [code, dark, id, attempt]);
  const ink = dark ? "#EEEFE9" : "#151515";
  return (
    <div
      style={{
        color: ink,
        fontFamily: "system-ui",
        padding: 8,
        boxSizing: "border-box",
        width: "100%",
      }}
    >
      <div
        ref={container}
        style={{ position: "absolute", visibility: "hidden", width: "100%" }}
      />
      {diagram ? (
        <iframe
          title="Mermaid diagram"
          sandbox=""
          srcDoc={diagram.html}
          style={{ border: 0, width: "100%", height: diagram.height }}
        />
      ) : (
        <output>
          {failed ? "Could not draw this diagram." : "Drawing diagram"}
        </output>
      )}
      {failed ? (
        <button type="button" onClick={() => setAttempt((value) => value + 1)}>
          Retry
        </button>
      ) : null}
      <button
        type="button"
        onClick={() => setShowSource(!showSource)}
        style={{
          background: "none",
          border: 0,
          color: ink,
          padding: "8px 0",
          minHeight: 44,
        }}
      >
        {showSource ? "Hide diagram source" : "Show diagram source"}
      </button>
      {showSource ? (
        <pre
          style={{
            whiteSpace: "pre-wrap",
            overflowWrap: "anywhere",
            fontSize: 12,
          }}
        >
          {code}
        </pre>
      ) : null}
    </div>
  );
}
