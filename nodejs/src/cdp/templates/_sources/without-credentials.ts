// A request often carries the caller's credential in the query string or body (?api_key=...),
// and a source template stores or prints whatever arrives. Templates prepend this Hog function
// to their code and pass each mapped object through it, so a key that names a credential never
// reaches an event, a person's properties or the function logs.
// It drops the matching top-level keys only. A credential nested deeper in the object stays.
// A flat bracketed key such as account[password] is judged by its last segment. CamelCase names
// are listed one by one, because a pattern cannot tell accessToken from designToken.
export const WITHOUT_CREDENTIALS_HOG = `
fun withoutCredentials(source) {
  if (typeof(source) != 'object') {
    return source
  }
  let kept := {}
  for (let key, value in source) {
    let name := replaceAll(replaceAll(replaceAll(lower(key), '-', '_'), '[', '.'), ']', '')
    let isCredential := match(name, '(^|[.])(auth|authorization|key|apikey|password|passwd|secret|signature|token|accesskey|accesstoken|refreshtoken|authtoken|idtoken|apitoken|sessiontoken|bearertoken|clientsecret|apisecret|secretkey|secretaccesskey|privatekey)$') or match(name, '(api_key|secret_key|access_key|private_key|_token|_secret|password)$')
    if (not isCredential) {
      kept[key] := value
    }
  }
  return kept
}
`
