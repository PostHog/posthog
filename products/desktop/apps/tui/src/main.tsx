import { render } from "ink";
import { TuiAuth } from "./auth";
import { Root } from "./components/Root";

const auth = TuiAuth.load();
const instance = render(<Root initialAuth={auth} />, { alternateScreen: true });

let reloading = false;
if (import.meta.hot) {
  // Component edits re-render in place, so the screen stays up.
  import.meta.hot.accept("./components/Root", (next) => {
    if (next) instance.rerender(<next.Root initialAuth={auth} />);
  });
  // Any other edit re-runs this module, so tear down this copy first.
  import.meta.hot.dispose(() => {
    reloading = true;
    instance.unmount();
  });
}

await instance.waitUntilExit();
if (!reloading) process.exit(0);
