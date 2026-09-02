export function isMcpOAuthRedirect(
  response: object,
): response is { redirect_url: string } {
  return (
    "redirect_url" in response && typeof response.redirect_url === "string"
  );
}

export function isStdioMcpServer(server: {
  transport_type?: string | null;
}): boolean {
  return server.transport_type === "stdio";
}
