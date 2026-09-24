// A request often carries the caller's credential in the query string or body (?api_key=...),
// and a source template stores or prints whatever arrives. Templates prepend this Hog function
// to their code and pass each mapped object through it, so a key that names a credential never
// reaches an event, a person's properties or the function logs.
// It drops the matching top-level keys only. A credential nested deeper in the object stays.
export const WITHOUT_CREDENTIALS_HOG = `
fun withoutCredentials(source) {
  if (typeof(source) != 'object') {
    return source
  }
  let kept := {}
  for (let key, value in source) {
    let name := replaceAll(lower(key), '-', '_')
    let isCredential := name in ['auth', 'authorization', 'key', 'apikey', 'password', 'secret', 'signature', 'token'] or name like '%api_key' or name like '%_token' or name like '%_secret' or name like '%password'
    if (not isCredential) {
      kept[key] := value
    }
  }
  return kept
}
`
