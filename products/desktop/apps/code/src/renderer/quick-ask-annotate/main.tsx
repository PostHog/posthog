import React from "react";
import { createRoot } from "react-dom/client";
import { Annotate } from "./Annotate";
import "./annotate.css";

const root = document.getElementById("root");
if (root) {
  createRoot(root).render(
    <React.StrictMode>
      <Annotate />
    </React.StrictMode>,
  );
}
