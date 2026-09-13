export class SessionConnectingError extends Error {
  constructor() {
    super("Session is still connecting.");
    this.name = "SessionConnectingError";
  }
}
