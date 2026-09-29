import { render } from "ink";
import { TuiAuth } from "./auth";
import { Root } from "./components/Root";

const instance = render(<Root initialAuth={TuiAuth.load()} />, {
  alternateScreen: true,
});

let reloading = false;
if (import.meta.hot) {
  // A swapped Root starts with fresh state, so it rereads the session a sign-in may have saved.
  import.meta.hot.accept("./components/Root", (next) => {
    if (next) instance.rerender(<next.Root initialAuth={TuiAuth.load()} />);
  });
  // Any other edit re-runs this module, so tear down this copy first.
  import.meta.hot.dispose(() => {
    reloading = true;
    instance.unmount();
  });
}

await instance.waitUntilExit();
if (!reloading) process.exit(0);
