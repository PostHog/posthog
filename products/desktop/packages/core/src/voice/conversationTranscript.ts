export interface VoiceTranscriptTurn {
  offset: number;
  speaker: "user" | "assistant";
  text: string;
}

export function parseVoiceTranscript(
  content: string,
): VoiceTranscriptTurn[] | null {
  const prefix = "Spoken conversation:\n";
  if (!content.startsWith(prefix)) return null;

  const turns: VoiceTranscriptTurn[] = [];
  let offset = prefix.length;
  for (const line of content.slice(prefix.length).split("\n")) {
    const match = /^(User|Voice assistant):[ \t]*(.*)$/.exec(line);
    if (match) {
      turns.push({
        offset,
        speaker: match[1] === "User" ? "user" : "assistant",
        text: match[2],
      });
    } else if (turns.length > 0) {
      turns[turns.length - 1].text += `\n${line}`;
    } else if (line.trim()) {
      return null;
    }
    offset += line.length + 1;
  }
  for (const turn of turns) turn.text = turn.text.trim();
  if (
    turns.some((turn) => !turn.text) ||
    !turns.some((turn) => turn.speaker === "user")
  ) {
    return null;
  }
  return turns;
}
