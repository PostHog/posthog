import { useQueryClient } from "@tanstack/react-query";
import type { ReactNode } from "react";

export const STORY_SCREENSHOT_PATHS = {
  heading: "/tmp/posthog-desktop/clipboard/comment-heading.png",
  button: "/tmp/posthog-desktop/clipboard/comment-button.png",
};

function drawScreenshot(kind: keyof typeof STORY_SCREENSHOT_PATHS): string {
  const width = 720;
  const height = 440;
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext("2d");
  if (!context) return "";
  context.scale(2, 2);
  context.fillStyle = "#fbfaf7";
  context.fillRect(0, 0, width, height);
  context.fillStyle = "#1d1f27";
  context.font = "600 12px system-ui";
  context.fillText("Acme", 20, 28);
  context.fillStyle = "#6b7280";
  context.font = "12px system-ui";
  context.fillText("Pricing   Docs   Blog", 220, 28);
  context.fillStyle = "#e5e7eb";
  context.fillRect(0, 44, width, 1);
  const target =
    kind === "heading"
      ? { x: 60, y: 86, w: 180, h: 40 }
      : { x: 60, y: 150, w: 132, h: 34 };
  context.fillStyle = "#1d1f27";
  context.font = "700 30px system-ui";
  context.fillText("Hot stuff", 64, 118);
  context.fillStyle = "#6b7280";
  context.font = "13px system-ui";
  context.fillText("Everything you need to ship faster.", 64, 140);
  context.fillStyle = "#1d4aff";
  context.beginPath();
  context.roundRect(64, 154, 124, 26, 6);
  context.fill();
  context.fillStyle = "#ffffff";
  context.font = "600 12px system-ui";
  context.fillText("Start free trial", 80, 171);
  context.strokeStyle = "#f54e00";
  context.lineWidth = 2;
  context.fillStyle = "rgba(245,78,0,0.12)";
  context.fillRect(target.x, target.y, target.w, target.h);
  context.strokeRect(target.x, target.y, target.w, target.h);
  const pinX = target.x + target.w;
  const pinY = target.y;
  context.save();
  context.translate(pinX, pinY);
  context.rotate(-Math.PI / 4);
  context.fillStyle = "#f54e00";
  context.strokeStyle = "#ffffff";
  context.beginPath();
  context.moveTo(-11, 0);
  context.arc(0, 0, 11, Math.PI, Math.PI / 2, false);
  context.lineTo(-11, 11);
  context.closePath();
  context.fill();
  context.stroke();
  context.restore();
  return canvas.toDataURL("image/png");
}

export function WithStoryScreenshots({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  for (const kind of Object.keys(STORY_SCREENSHOT_PATHS) as Array<
    keyof typeof STORY_SCREENSHOT_PATHS
  >) {
    const key = ["os", "readFileAsDataUrl", STORY_SCREENSHOT_PATHS[kind]];
    if (!queryClient.getQueryData(key)) {
      queryClient.setQueryData(key, drawScreenshot(kind));
    }
  }
  return <>{children}</>;
}
