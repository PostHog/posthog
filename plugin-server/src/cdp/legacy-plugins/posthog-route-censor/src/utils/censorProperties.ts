import { Properties } from '@posthog/plugin-scaffold';
import { Routes } from 'types';
import { censorUrlPath, checkIsValidHttpUrl } from 'utils';

/**
 * Removes addresses and hashes from URLs stored in posthog properties.
 *
 * @param properties Full list of properties passed into the event.
 * @param propertiesToAnonymize List of properties that should be anonymized.
 * @returns The anonymized list of properties.
 */
export const censorProperties = (
  properties: Properties | undefined,
  routes: Routes | undefined,
  propertiesToAnonymize: string[],
): Partial<Properties> => {
  if (!properties) return {};
  const censoredProperties: Partial<Properties> = {};

  propertiesToAnonymize.forEach((propertyKey) => {
    const propertyValue = properties[propertyKey];
    if (!propertyValue || typeof propertyValue !== 'string') {
      return;
    }

    const isValidUrl = checkIsValidHttpUrl(propertyValue);
    // For full URLs, first parse out the path.
    if (isValidUrl) {
      const url = new URL(propertyValue);
      const censoredPath = censorUrlPath(url.pathname, routes);
      // Piece back together the URL but with the censored path.
      censoredProperties[propertyKey] = `${url.origin}${censoredPath}`;
      return;
    }
    // Otherwise assume the propertyValue is a url path (instead of the full url) and we can censor it directly.
    censoredProperties[propertyKey] = censorUrlPath(propertyValue, routes);
  });

  return censoredProperties;
};
