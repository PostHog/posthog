import { matchRoutes } from '@remix-run/router';
import { Routes } from 'types';

/**
 * Take a URL path and applies the react router v6 route matching algorithm
 * to censor portions of the URL
 *
 * @param path URL path to censor
 * @returns same URL path, but with all included variables censored
 */
export const censorUrlPath = (path: string, routes?: Routes) => {
  if (typeof path !== 'string') {
    return path;
  }

  // If no routes, then just censor all paths to be safe.
  if (typeof routes === 'undefined') {
    return '/:censoredFullPath';
  }

  // Find matches with URL path using React Router's parsing algoritm.
  const matches = matchRoutes(routes, path);

  // If no matches, then no need to censor anything.
  if (!matches?.length) {
    return path;
  }

  let censoredPath = path;
  // Check each match, if the variable is in the "includes" array, then censor it.
  matches.forEach((match) => {
    match.route.include.forEach((variableToCensor) => {
      const value = match.params[variableToCensor];
      if (!value) {
        return;
      }
      censoredPath = censoredPath.replace(value, `:${variableToCensor}`);
    });
  });
  return censoredPath;
};
