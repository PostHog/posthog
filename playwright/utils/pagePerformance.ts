/**
 * Utilities to disable animations and transitions in Playwright tests.
 * This makes tests more reliable and faster by eliminating timing-dependent animations.
 */

/**
 * CSS that disables all animations and transitions with !important.
 * This is the single source of truth for test performance optimization.
 */
export const DISABLE_ANIMATIONS_CSS = `
  *,
  *::before,
  *::after {
    transition-property: none !important;
    transition-duration: 0s !important;
    transition-delay: 0s !important;
    animation: none !important;
    animation-duration: 0s !important;
    animation-delay: 0s !important;
    scroll-behavior: auto !important;
  }
`

/**
 * Creates an init script function for use with context.addInitScript().
 * This injects the CSS and disables animation-related APIs before any page loads.
 *
 * Using context.addInitScript() ensures the script runs on EVERY page load,
 * including after navigation and reloads, making it persistent across the test session.
 *
 * @returns A function to be passed to context.addInitScript()
 *
 * @example
 * ```ts
 * import { createDisableAnimationsInitScript } from './pagePerformance'
 *
 * context: async ({ context }, use) => {
 *     await context.addInitScript(createDisableAnimationsInitScript())
 *     await use(context)
 * }
 * ```
 */
export const createDisableAnimationsInitScript = (): string =>
    `(function () {
    var css = ${JSON.stringify(DISABLE_ANIMATIONS_CSS)};
    
    function injectStyle() {
      // Guard against duplicate injection
      if (document.getElementById('posthog-test-disable-animations')) {
        return;
      }
      
      var styleTag = document.createElement('style');
      styleTag.type = 'text/css';
      styleTag.id = 'posthog-test-disable-animations';
      styleTag.appendChild(document.createTextNode(css));
      
      var target = document.head || document.documentElement;
      if (target) {
        target.appendChild(styleTag);
      }
    }
    
    // If document is already loaded or loading, inject immediately
    if (document.documentElement) {
      injectStyle();
    } else {
      // Otherwise wait for the document to be created
      var observer = new MutationObserver(function() {
        if (document.documentElement) {
          observer.disconnect();
          injectStyle();
        }
      });
      observer.observe(document, { childList: true, subtree: true });
    }
  })();`
