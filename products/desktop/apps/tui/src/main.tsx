import { render } from "ink";
import { TuiAuth } from "./auth";
import { Root } from "./components/Root";
import { MouseInput } from "./mouse";

const mouse = new MouseInput();
const root = (Component: typeof Root) => (
  <Component initialAuth={TuiAuth.load()} clicks={mouse.clicks} />
);
const instance = render(root(Root), {
  stdin: mouse.stdin,
  alternateScreen: true,
  exitOnCtrlC: false,
  // Forced on so Cmd and Ctrl+Shift arrive as modifiers where the terminal supports it; others ignore it.
  kittyKeyboard: { mode: "enabled" },
});
mouse.enable();

let reloading = false;
if (import.meta.hot) {
  // A swapped Root starts with fresh state, so it rereads the session a sign-in may have saved.
  import.meta.hot.accept("./components/Root", (next) => {
    if (next) instance.rerender(root(next.Root));
  });
  // Any other edit re-runs this module, so tear down this copy first.
  import.meta.hot.dispose(() => {
    reloading = true;
    mouse.dispose();
    instance.unmount();
  });
}

await instance.waitUntilExit();
if (!reloading) {
  mouse.dispose();
  process.exit(0);
}
