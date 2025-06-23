import { CodeSnippet, Language } from 'lib/components/CodeSnippet'

import { SDKInstallAngularInstructions } from '../sdk-install-instructions'
import { JSManualCapture } from './FinalSteps'

export function AngularInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallAngularInstructions />
            <Autocapture />
            <JSManualCapture />
        </>
    )
}

const Autocapture = (): JSX.Element => {
    return (
        <>
            <h3>Capturing exceptions</h3>
            <p>
                Exception autocapture can be enabled during initialization of the PostHog client to automatically
                capture any exception thrown by your Angular application.
            </p>
            <p>You will need to override Angular's default ErrorHandler provider:</p>
            <CodeSnippet language={Language.JavaScript}>{autocaptureHandler}</CodeSnippet>
            <p>
                Then, in your <code>src/app/app.config.ts</code>, import the <code>providePostHogErrorHandler</code>{' '}
                function and add it to the providers array:
            </p>
            <CodeSnippet language={Language.JavaScript}>{appConfig}</CodeSnippet>
        </>
    )
}

const autocaptureHandler = `// src/app/posthog-error-handler.ts

import { ErrorHandler, Injectable, Provider } from '@angular/core';
import { HttpErrorResponse } from '@angular/common/http';

import posthog from 'posthog-js';

/**
 * Implementation of Angular's ErrorHandler provider that can be used as a drop-in replacement for the stock one.
 */
@Injectable({ providedIn: 'root' })
class PostHogErrorHandler implements ErrorHandler {
  public constructor() {}

  /**
   * Method called for every value captured through the ErrorHandler
   */
  public handleError(error: unknown): void {
    const extractedError = this._extractError(error) || 'Unknown error';
    runOutsideAngular(() => posthog.captureException(extractedError));
  }

  protected _extractError(errorCandidate: unknown): unknown {
    const error = tryToUnwrapZonejsError(errorCandidate);

    if (error instanceof HttpErrorResponse) {
      return extractHttpModuleError(error);
    }

    if (typeof error === 'string' || isErrorOrErrorLikeObject(error)) {
      return error;
    }

    return null;
  }
}

// https://github.com/angular/angular/blob/master/packages/core/src/util/errors.ts
function tryToUnwrapZonejsError(error: unknown): unknown | Error {
  // TODO: once Angular14 is the minimum requirement ERROR_ORIGINAL_ERROR and
  //  getOriginalError from error.ts can be used directly.
  return error && (error as { ngOriginalError: Error }).ngOriginalError
    ? (error as { ngOriginalError: Error }).ngOriginalError
    : error;
}

function extractHttpModuleError(error: HttpErrorResponse): string | Error {
  // The \`error\` property of http exception can be either an \`Error\` object, which we can use directly...
  if (isErrorOrErrorLikeObject(error.error)) {
    return error.error;
  }

  // ... or an \`ErrorEvent\`, which can provide us with the message but no stack...
  // guarding \`ErrorEvent\` against \`undefined\` as it's not defined in Node environments
  if (
    typeof ErrorEvent !== 'undefined' &&
    error.error instanceof ErrorEvent &&
    error.error.message
  ) {
    return error.error.message;
  }

  // ...or the request body itself, which we can use as a message instead.
  if (typeof error.error === 'string') {
    return \`Server returned code \${error.status} with body "\${error.error}"\`;
  }

  // If we don't have any detailed information, fallback to the request message itself.
  return error.message;
}

function isErrorOrErrorLikeObject(value: unknown): value is Error {
  if (value instanceof Error) {
    return true;
  }

  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    return false;
  }

  return 'name' in value && 'message' in value && 'stack' in value;
}

// This would be exposed in the global environment whenever \`zone.js\` is
// included in the \`polyfills\` configuration property. Starting from Angular 17,
// users can opt-in to use zoneless change detection.
declare const Zone: any;

// In Angular 17 and future versions, zoneless support is forthcoming.
// Therefore, it's advisable to safely check whether the \`run\` function is
// available in the \`<root>\` context.
// eslint-disable-next-line @typescript-eslint/no-unsafe-member-access
const isNgZoneEnabled = typeof Zone !== 'undefined' && Zone.root?.run;

export function runOutsideAngular<T>(callback: () => T): T {
  // Running the \`callback\` within the root execution context enables Angular
  // processes (such as SSR and hydration) to continue functioning normally without
  // timeouts and delays that could affect the user experience. This approach is
  // necessary because some of the error tracking functionality continues to run in the background.
  // eslint-disable-next-line @typescript-eslint/no-unsafe-member-access
  return isNgZoneEnabled ? Zone.root.run(callback) : callback();
}

export function providePostHogErrorHandler(): Provider {
  return {
    provide: ErrorHandler,
    useValue: new PostHogErrorHandler(),
  };
}
`

const appConfig = `// src/app/app.config.ts

import { ApplicationConfig } from '@angular/core';
import { providePostHogErrorHandler } from './posthog-error-handler';

export const appConfig: ApplicationConfig = {
  providers: [
    ...
    providePostHogErrorHandler(),
  ],
};
`
