import { ServiceProvider } from "@posthog/di/react";
import { CodePreview } from "@posthog/ui/features/sessions/components/session-update/CodePreview";
import { DIFF_WORKER_FACTORY } from "@posthog/ui/shell/diffWorkerHost";
import { render, waitFor } from "@testing-library/react";
import { Container } from "inversify";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import { DiffWorkerPool } from "./DiffWorkerPool";

// The pool manager only ever calls these four members on a worker, and it never
// reads a reply, so a stub is enough to observe how many workers a mount starts
// and when they stop.
function createWorkerStub() {
  return {
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    postMessage: vi.fn(),
    terminate: vi.fn(),
  };
}

function renderWithFactory(children: ReactNode) {
  const workers: ReturnType<typeof createWorkerStub>[] = [];
  const workerFactory = vi.fn(() => {
    const worker = createWorkerStub();
    workers.push(worker);
    return worker as unknown as Worker;
  });
  const container = new Container();
  container.bind(DIFF_WORKER_FACTORY).toConstantValue(workerFactory);

  const view = render(
    <ServiceProvider container={container}>{children}</ServiceProvider>,
  );
  return { ...view, workers, workerFactory };
}

describe("DiffWorkerPool", () => {
  it("starts no workers for a preview that renders no diff", async () => {
    const { workerFactory, findByText } = renderWithFactory(
      <CodePreview
        content="const answer = 42;"
        filePath="answer.ts"
        showPath
      />,
    );

    await findByText("answer.ts", { exact: false });
    // A conversation that shows code but no diff must not pay for the pool.
    expect(workerFactory).not.toHaveBeenCalled();
  });

  it("caps a mounted pool at two workers and shares it across concurrent diffs", async () => {
    const { workers, unmount } = renderWithFactory(
      <>
        <DiffWorkerPool>
          <span>first diff</span>
        </DiffWorkerPool>
        <DiffWorkerPool>
          <span>second diff</span>
        </DiffWorkerPool>
      </>,
    );

    // Two mounted diffs, one renderer-wide pool: two workers, not four.
    await waitFor(() => expect(workers).toHaveLength(2));
    unmount();
  });

  it("stops the workers only once the last diff unmounts", async () => {
    function Diffs({ second }: { second: boolean }) {
      return (
        <>
          <DiffWorkerPool>
            <span>first diff</span>
          </DiffWorkerPool>
          {second && (
            <DiffWorkerPool>
              <span>second diff</span>
            </DiffWorkerPool>
          )}
        </>
      );
    }

    const { workers, rerender, unmount, workerFactory } = renderWithFactory(
      <Diffs second={true} />,
    );
    await waitFor(() => expect(workers).toHaveLength(2));

    const container = new Container();
    container.bind(DIFF_WORKER_FACTORY).toConstantValue(workerFactory);
    rerender(
      <ServiceProvider container={container}>
        <Diffs second={false} />
      </ServiceProvider>,
    );
    for (const worker of workers) {
      expect(worker.terminate).not.toHaveBeenCalled();
    }

    unmount();
    await waitFor(() => {
      for (const worker of workers) {
        expect(worker.terminate).toHaveBeenCalled();
      }
    });
    // Releasing the pool must not quietly restart it.
    expect(workerFactory).toHaveBeenCalledTimes(2);
  });
});
