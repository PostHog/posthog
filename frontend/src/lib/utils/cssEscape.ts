/*!
 we used to use https://mths.be/cssescape v1.5.1 by @mathias | MIT license
 but the `finder` dependency has always been using `CSS.escape` from the browser
 and nobody has ever pointed out an error
 cssEscape function was only for IE11 users
 and they mustn't be using this anyway
 */
export const cssEscape = CSS.escape
