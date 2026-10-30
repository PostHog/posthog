import { render } from "ink";
import { App } from "./components/App";

const instance = render(<App />, { alternateScreen: true });

let reloading = false;
if (import.meta.hot) {
  // Component edits re-render in place, so the screen stays up.
  import.meta.hot.accept("./components/App", (next) => {
    if (next) instance.rerender(<next.App />);
  });
  // Any other edit re-runs this module, so tear down this copy first.
  import.meta.hot.dispose(() => {
    reloading = true;
    instance.unmount();
  });
}

await instance.waitUntilExit();
if (!reloading) process.exit(0);
