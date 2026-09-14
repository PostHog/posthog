import { Annotate } from "@posthog/quick-ask/annotate/Annotate";
import React from "react";
import { createRoot } from "react-dom/client";
import "@posthog/quick-ask/annotate/annotate.css";

const root = document.getElementById("root");
if (root) {
  createRoot(root).render(
    <React.StrictMode>
      <Annotate />
    </React.StrictMode>,
  );
}
