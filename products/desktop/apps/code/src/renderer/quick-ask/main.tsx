import React from "react";
import ReactDOM from "react-dom/client";
import { QuickAsk } from "./QuickAsk";
import "./quick-ask.css";

const root = document.getElementById("root");
if (root) {
  ReactDOM.createRoot(root).render(
    <React.StrictMode>
      <QuickAsk />
    </React.StrictMode>,
  );
}
