export interface AmplitudeUserProperties {
  $set?: object
  $setOnce?: object
  [k: string]: unknown
}

export function mergeUserProperties(...properties: AmplitudeUserProperties[]): AmplitudeUserProperties {
  return properties.reduce((prev, current) => {
    const hasSet = prev.$set || current.$set
    const hasSetOnce = prev.$setOnce || current.$setOnce
    return {
      ...prev,
      ...current,
      ...(hasSet && { $set: { ...prev.$set, ...current.$set } }),
      ...(hasSetOnce && { $setOnce: { ...prev.$setOnce, ...current.$setOnce } })
    }
  }, {})
}
