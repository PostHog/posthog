import { Page } from '@playwright/test'

/**
 * Utilities to disable animations and transitions in Playwright tests.
 * This makes tests more reliable and faster by eliminating timing-dependent animations.
 */

/**
 * CSS that disables all animations and transitions with !important.
 * This is the single source of truth for test performance optimization.
 *
 * Targets all PostHog frontend animations including:
 * - CSS transitions (opacity, transform, color, etc.)
 * - Keyframe animations (shimmer, pulse, spin, etc.)
 * - Chart.js animations
 * - Lemon UI component transitions
 */
export const DISABLE_ANIMATIONS_CSS = `
  *,
  *::before,
  *::after {
    /* Disable all CSS transitions */
    transition-property: none !important;
    transition-duration: 0s !important;
    transition-delay: 0s !important;
    
    /* Disable all CSS animations */
    animation: none !important;
    animation-duration: 0s !important;
    animation-delay: 0s !important;
    animation-iteration-count: 1 !important;
    animation-play-state: paused !important;
    
    /* Disable smooth scrolling */
    scroll-behavior: auto !important;
  }
  
  /* Force reduced motion preference for components that check it */
  @media (prefers-reduced-motion: no-preference) {
    *,
    *::before,
    *::after {
      animation: none !important;
      transition: none !important;
    }
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
    
    // Override requestAnimationFrame to run immediately (already done in context)
    window.requestAnimationFrame = function(callback) { return window.setTimeout(callback, 0); };
    window.cancelAnimationFrame = function(id) { window.clearTimeout(id); };
    
    // Disable Web Animations API
    if (window.Element && window.Element.prototype.animate) {
      window.Element.prototype.animate = function() { 
        return { 
          cancel: function() {}, 
          finish: function() {},
          play: function() {},
          pause: function() {},
          reverse: function() {},
          get currentTime() { return 0; },
          set currentTime(value) {},
          get playState() { return 'finished'; }
        }; 
      };
    }
    
    // Disable CSS.supports checks for animations (some libs check this)
    if (window.CSS && window.CSS.supports) {
      var originalSupports = window.CSS.supports;
      window.CSS.supports = function(property, value) {
        if (property && property.includes('animation')) return false;
        if (property && property.includes('transition')) return false;
        return originalSupports.apply(this, arguments);
      };
    }
  })()
`

/**
 * Disables animations and transitions on a specific page.
 * Use this when you need to disable animations for a single page rather than globally.
 *
 * @param page - The Playwright Page object
 *
 * @example
 * ```ts
 * import { disableAnimations } from './pagePerformance'
 *
 * test('my test', async ({ page }) => {
 *     await disableAnimations(page)
 *     // ... test code
 * })
 * ```
 */
export async function disableAnimations(page: Page): Promise<void> {
    await page.evaluate((css) => {
        // Guard against duplicate injection
        if (document.getElementById('posthog-test-disable-animations')) {
            return
        }

        const style = document.createElement('style')
        style.id = 'posthog-test-disable-animations'
        style.textContent = css
        document.head?.appendChild(style)

        // Override requestAnimationFrame to run immediately
        window.requestAnimationFrame = function (callback) {
            return window.setTimeout(callback, 0)
        }
        window.cancelAnimationFrame = function (id) {
            window.clearTimeout(id)
        }

        // Disable Web Animations API
        if (window.Element && window.Element.prototype.animate) {
            const mockAnimation = {
                cancel: function () {},
                finish: function () {},
                play: function () {},
                pause: function () {},
                reverse: function () {},
                get currentTime() {
                    return 0
                },
                set currentTime(value) {},
                get playState() {
                    return 'finished'
                },
            } as unknown as Animation

            window.Element.prototype.animate = function () {
                return mockAnimation
            }
        }

        // Disable CSS.supports checks for animations
        if (window.CSS && window.CSS.supports) {
            const originalSupports = window.CSS.supports
            window.CSS.supports = function (property: string, value?: string) {
                if (property && property.includes('animation')) {
                    return false
                }
                if (property && property.includes('transition')) {
                    return false
                }
                if (value === undefined) {
                    return originalSupports(property)
                }
                return originalSupports(property, value)
            }
        }
    }, DISABLE_ANIMATIONS_CSS)
}

/**
 * Dismisses billing alert banners by clicking their close button.
 *
 * This function waits for the billing alert close button and clicks it,
 * then verifies the banner is no longer visible.
 *
 * @example
 * ```ts
 * import { hideBillingAlerts } from './pagePerformance'
 *
 * test('my test', async ({ page }) => {
 *     await hideBillingAlerts(page)
 *     // ... test code
 * })
 * ```
 */
export async function hideBillingAlerts(page: Page): Promise<void> {
    const closeButton = page.getByTestId('lemon-banner-close')

    // Wait for the close button to be available (with timeout in case there's no alert)
    try {
        await closeButton.waitFor({ state: 'visible', timeout: 3000 })
        await closeButton.click()
        // Assert the banner is no longer visible
        await page.getByTestId('lemon-banner').waitFor({ state: 'hidden', timeout: 2000 })
    } catch {
        // No billing alert found - that's fine, just continue
    }
}
