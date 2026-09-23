import "reflect-metadata";
import { ApiRequestError } from "@posthog/api-client/fetcher";
import {
  LIVE_VOICE_TRANSPORT,
  type LiveVoiceTransport,
  type VoiceAudioLevels,
} from "@posthog/platform/speech";
import { decorate, inject, injectable } from "inversify";
import {
  isVoiceErrorState,
  liveVoiceEventSchema,
  type VoiceErrorState,
  type VoiceState,
  type VoiceToolCall,
  voiceAnswerArgumentsSchema,
  voiceTaskArgumentsSchema,
} from "./schemas";

import {
  type VoiceQuestion,
  type VoiceQuestionAnswer,
  type VoiceQuestionDraft,
  voiceQuestionDraftAnswers,
} from "./voiceQuestion";

interface PendingVoiceQuestion {
  request: VoiceQuestion;
  index: number;
  answers: Record<string, string>;
}

export interface VoiceConversation {
  createSession(sdp: string, signal: AbortSignal): Promise<string>;
  sendMessage(text: string): Promise<boolean>;
  answerQuestion?(
    id: string,
    answers: Record<string, string>,
  ): Promise<boolean>;
  onQuestionAnswer?(answer: VoiceQuestionAnswer): void;
  onToolCall?(call: VoiceToolCall): void;
  onState(state: VoiceState): void;
  onAudioLevels?(levels: VoiceAudioLevels): void;
  onEnded(result: {
    sessionId: string | null;
    seconds: number | null;
    finalized: boolean;
    failed: boolean;
  }): void;
}

export const CONVERSATION_VOICE_SESSION = Symbol.for("posthog.voice.session");
export type VoiceSessionFactory = (
  conversation: VoiceConversation,
) => ConversationVoiceSession;
export const VOICE_SESSION_FACTORY = Symbol.for("posthog.voice.sessionFactory");
export const VOICE_CONVERSATION = Symbol.for("posthog.voice.conversation");

// UTF-8 bytes bound token count, including non-Latin text and emoji.
export function voiceCommentaryChunks(text: string): string[] {
  const chunks: string[] = [];
  let chunk = "";
  let bytes = 0;
  for (const char of text) {
    const code = char.codePointAt(0) ?? 0;
    const size = code < 0x80 ? 1 : code < 0x800 ? 2 : code < 0x10000 ? 3 : 4;
    if (bytes + size > 480) {
      chunks.push(chunk);
      chunk = "";
      bytes = 0;
    }
    chunk += char;
    bytes += size;
  }
  if (chunk) chunks.push(chunk);
  return chunks;
}

export class ConversationVoiceSession {
  private state: VoiceState = "idle";
  private generation = 0;
  private readonly seen = new Set<string>();
  private transcripts: {
    role: string;
    text: string;
    start: number;
    end: number;
  }[] = [];
  private reply = "";
  private pendingReply: string | null = null;
  private question: PendingVoiceQuestion | null = null;
  private dispatch = Promise.resolve();
  private questionDispatch = Promise.resolve();
  private structuredTools = false;
  private readonly toolResponses = new Map<
    string,
    { id: string; calls: Promise<void>[] }
  >();
  private timeout: ReturnType<typeof setTimeout> | undefined;
  private readonly delegationTimers = new Set<ReturnType<typeof setTimeout>>();
  private abort: AbortController | undefined;
  private sessionId: string | null = null;
  private seconds: number | null = null;

  constructor(
    private readonly transport: LiveVoiceTransport,
    private readonly conversation: VoiceConversation,
  ) {}

  private setState(state: VoiceState): void {
    this.state = state;
    this.conversation.onState(state);
  }

  private append(content: string, delegationId: string | null = null): void {
    if (this.state !== "connected" || !content.trim()) return;
    for (const chunk of voiceCommentaryChunks(content)) {
      this.transport.send(
        JSON.stringify({
          type: "session.commentary.append",
          delegation_id: delegationId,
          content: chunk,
        }),
      );
    }
  }

  updateQuestion(
    request: VoiceQuestion | null,
    draft?: VoiceQuestionDraft,
  ): void {
    const index = request
      ? Math.max(0, Math.min(draft?.activeStep ?? 0, request.questions.length))
      : 0;
    const answers =
      request && draft ? voiceQuestionDraftAnswers(request, draft) : {};
    const sameQuestion = request?.id === this.question?.request.id;
    const sameIndex = index === this.question?.index;
    if (
      sameQuestion &&
      sameIndex &&
      JSON.stringify(answers) === JSON.stringify(this.question?.answers ?? {})
    )
      return;
    this.question = request ? { request, index, answers } : null;
    this.syncQuestionContext();
    if (!sameQuestion || !sameIndex) this.announceQuestion();
  }

  private announceQuestion(delegationId: string | null = null): void {
    if (!this.question || this.state !== "connected") return;
    const { request, index } = this.question;
    const question = request.questions[index];
    if (!question) {
      this.append(
        "Review your answers and select Submit in the app.",
        delegationId,
      );
      return;
    }
    const content = [
      `Current clarification question ${index + 1} of ${request.questions.length}: ${question.question}`,
      ...(question.multiSelect
        ? ["The user can choose more than one option."]
        : []),
      ...question.options.map(
        (option, i) =>
          `${i + 1}. ${option.label}${option.description ? `: ${option.description}` : ""}`,
      ),
    ].join("\n");
    // boffin: Commentary carries the question without a later instruction interrupting its speech.
    this.append(content, delegationId);
  }

  private questionContext(): object | null {
    if (!this.question) return null;
    const { request, index, answers } = this.question;
    const question = request.questions[index];
    if (!question)
      return {
        question_id: null,
        recorded_answers: answers,
        message:
          "The user is reviewing their answers. They can submit or edit them in the app.",
      };
    return {
      question_id: `${request.id}:${index}`,
      question_number: index + 1,
      total_questions: request.questions.length,
      question: question.question,
      multi_select: question.multiSelect ?? false,
      options: question.options.map((option, i) => ({
        id: `option_${i}`,
        ...option,
      })),
      recorded_answers: answers,
    };
  }

  private syncQuestionContext(): void {
    if (!this.structuredTools || this.state !== "connected") return;
    this.transport.send(
      JSON.stringify({
        type: "response.item.create",
        item: {
          type: "message",
          role: "user",
          content: [
            {
              type: "input_text",
              text: `Application state, not a new user request: ${JSON.stringify({ pending_question: this.questionContext() })}`,
            },
          ],
        },
      }),
    );
  }

  private async answerStructuredQuestion(
    input: unknown,
    question: PendingVoiceQuestion | null,
    generation: number,
  ): Promise<object> {
    const parsed = voiceAnswerArgumentsSchema.safeParse(input);
    if (!parsed.success)
      return {
        error: "Invalid answer arguments. Ask the user to repeat their answer.",
      };
    if (
      generation !== this.generation ||
      this.state !== "connected" ||
      !question ||
      this.question !== question
    )
      return {
        error: "That question is no longer pending.",
        pending_question: this.questionContext(),
      };
    const { question_id, option_ids, custom_answer } = parsed.data;
    if (question_id !== `${question.request.id}:${question.index}`)
      return {
        error: "Answer only the current question.",
        pending_question: this.questionContext(),
      };
    const item = question.request.questions[question.index];
    if (!item)
      return { error: "The user is reviewing their answers in the app." };
    const selectedIds = [...new Set(option_ids)];
    const selectedOptions = selectedIds.map((id) =>
      item.options.find((_, i) => id === `option_${i}`),
    );
    if (
      selectedOptions.some((option) => !option) ||
      (!item.multiSelect && selectedIds.length > 1)
    )
      return { error: "The selected options are not valid for this question." };
    const answer = [
      ...selectedOptions.map((option) => option?.label ?? ""),
      custom_answer.trim(),
    ]
      .filter(Boolean)
      .join(", ");
    if (!answer) return { error: "No answer was given. Keep listening." };
    const answers = { ...question.answers, [item.question]: answer };
    const nextIndex = question.index + 1;
    const answeredQuestion = { ...question, index: nextIndex, answers };
    // boffin: Publish recorded answers before updating the shared question form.
    this.question = answeredQuestion;
    this.conversation.onQuestionAnswer?.({
      toolCallId: question.request.toolCallId,
      questionIndex: question.index,
      selectedIds,
      customInput: custom_answer.trim(),
      nextIndex,
    });
    if (nextIndex < question.request.questions.length)
      return { recorded_answer: answer, next_question: this.questionContext() };
    let accepted = false;
    try {
      accepted =
        (await this.conversation.answerQuestion?.(
          question.request.id,
          answers,
        )) ?? false;
    } catch {
      // Keep the recorded choices available for retry in the app.
    }
    if (generation !== this.generation || this.state !== "connected")
      return { error: "Voice ended." };
    if (!accepted)
      return {
        error:
          "The answers were not sent. Ask the user to retry or use the app.",
      };
    if (this.question === answeredQuestion) this.question = null;
    return {
      recorded_answer: answer,
      submitted: true,
      message: "All answers were sent. The task is continuing.",
    };
  }

  private async executeToolCall(
    call: { call_id: string; name: string; arguments: string },
    generation: number,
  ): Promise<object> {
    let input: unknown;
    try {
      input = JSON.parse(call.arguments);
    } catch {
      return { error: "Invalid tool arguments." };
    }
    if (call.name === "answer_question") {
      const question = this.question;
      const item = question?.request.questions[question.index];
      const activity: VoiceToolCall = {
        id: call.call_id,
        name: "answer_question",
        input: item?.question ?? "Question",
        status: "running",
      };
      this.conversation.onToolCall?.(activity);
      const pending = this.questionDispatch.then(() =>
        this.answerStructuredQuestion(input, question, generation),
      );
      this.questionDispatch = pending.then(
        () => {},
        () => {},
      );
      const result = await pending;
      if (generation === this.generation)
        this.conversation.onToolCall?.({
          ...activity,
          status: "error" in result ? "failed" : "completed",
          result:
            "recorded_answer" in result
              ? String(result.recorded_answer)
              : "Answer was not recorded. Try again.",
        });
      return result;
    }
    if (call.name === "send_to_task") {
      const parsed = voiceTaskArgumentsSchema.safeParse(input);
      if (!parsed.success) return { error: "A task message is required." };
      if (this.question)
        return {
          error:
            "The task is waiting for clarification. Answer it or explain its options.",
          pending_question: this.questionContext(),
        };
      const activity: VoiceToolCall = {
        id: call.call_id,
        name: "send_to_task",
        input: parsed.data.text,
        status: "running",
      };
      this.conversation.onToolCall?.(activity);
      // Return before task completion so clarification tools can resume the same turn.
      void this.conversation
        .sendMessage(`Spoken conversation:\nUser: ${parsed.data.text}`)
        .then(
          (accepted) => {
            if (generation !== this.generation) return;
            this.conversation.onToolCall?.({
              ...activity,
              status: accepted ? "completed" : "failed",
            });
            if (!accepted)
              this.append(
                "Your message was not sent. Please use the text box to try again.",
              );
          },
          () => {
            if (generation !== this.generation) return;
            this.conversation.onToolCall?.({ ...activity, status: "failed" });
            this.append(
              "Your message was not sent. Please use the text box to try again.",
            );
          },
        );
      return {
        status: "dispatched",
        message:
          "Delivery is in progress. The task will report its result separately. Do not claim the work is complete.",
      };
    }
    return { error: "This voice tool is not available." };
  }

  private receiveToolEvent(
    event: Extract<
      ReturnType<typeof liveVoiceEventSchema.parse>,
      { type: "response.event" }
    >["event"],
    delegationId: string,
    generation: number,
  ): void {
    if (event.type === "response.created") {
      this.toolResponses.set(delegationId, {
        id: event.response.id,
        calls: [],
      });
      return;
    }
    const response = this.toolResponses.get(delegationId);
    if (!response) return;
    if (event.type === "response.output_item.done") {
      const key = `tool:${event.item.call_id}`;
      if (this.seen.has(key)) return;
      this.seen.add(key);
      const pending = this.executeToolCall(event.item, generation)
        .catch(() => ({
          error: "The voice action failed. Use the app to continue.",
        }))
        .then((result) => {
          if (generation !== this.generation || this.state !== "connected")
            return;
          this.transport.send(
            JSON.stringify({
              type: "response.item.create",
              item: {
                type: "function_call_output",
                call_id: event.item.call_id,
                output: JSON.stringify(result),
              },
            }),
          );
        });
      response.calls.push(pending);
      return;
    }
    if (event.response.id !== response.id) return;
    const { calls } = response;
    this.toolResponses.delete(delegationId);
    if (event.response.status !== "completed") {
      this.append(
        "Voice could not process that request. Please try again or use the app.",
      );
      return;
    }
    if (!calls?.length) return;
    void Promise.all(calls).then(() => {
      if (generation !== this.generation || this.state !== "connected") return;
      this.transport.send(JSON.stringify({ type: "response.create" }));
    });
  }

  private async answerQuestion(
    question: PendingVoiceQuestion,
    answer: string,
    delegationId: string,
    generation: number,
  ): Promise<void> {
    const item = question.request.questions[question.index];
    if (!item) {
      this.announceQuestion(delegationId);
      return;
    }
    const answers = {
      ...question.answers,
      [item.question]: answer,
    };
    if (question.index + 1 < question.request.questions.length) {
      this.question = { ...question, index: question.index + 1, answers };
      this.announceQuestion(delegationId);
      return;
    }
    let accepted = false;
    try {
      accepted =
        (await this.conversation.answerQuestion?.(
          question.request.id,
          answers,
        )) ?? false;
    } catch {
      // Keep the question available for a spoken retry.
    }
    if (generation !== this.generation || this.state !== "connected") return;
    if (accepted && this.question === question) this.question = null;
    this.append(
      accepted
        ? "The answer was sent to the task agent. Wait for its result before claiming that the work is complete."
        : "Your answer was not sent. Please answer the question again or use its controls in the app.",
      delegationId,
    );
  }

  private delegate(
    id: string,
    offset: number,
    generation: number,
    question: PendingVoiceQuestion | null,
  ): void {
    if (generation !== this.generation || this.state !== "connected") return;
    const parts = this.transcripts
      .filter((part) => part.start <= offset)
      .sort((a, b) => a.start - b.start);
    this.transcripts = this.transcripts.filter((part) => part.start > offset);
    if (!parts.some((part) => part.role === "User" && part.text.trim())) {
      this.append("I did not receive your request. Please say it again.", id);
      return;
    }
    const turns: { role: string; text: string }[] = [];
    for (const part of parts) {
      const previous = turns.at(-1);
      if (previous?.role === part.role) previous.text += part.text;
      else turns.push({ role: part.role, text: part.text });
    }
    const text = turns.map((part) => `${part.role}: ${part.text}`).join("\n");
    const dispatch = async (): Promise<void> => {
      if (generation !== this.generation || this.state !== "connected") return;
      // boffin: A spoken answer belongs only to the question that was pending when it arrived.
      if (question !== this.question) {
        this.announceQuestion(id);
        return;
      }
      if (question) {
        await this.answerQuestion(
          question,
          turns
            .filter((turn) => turn.role === "User")
            .map((turn) => turn.text)
            .join("\n")
            .trim(),
          id,
          generation,
        );
        return;
      }
      let accepted = false;
      try {
        accepted = await this.conversation.sendMessage(
          `Spoken conversation:\n${text}`,
        );
      } catch {
        /* Report delivery failure through voice. */
      }
      if (generation !== this.generation) return;
      this.append(
        accepted
          ? "The request was sent to the task agent. Wait for its result before claiming that the work is complete."
          : "Your message was not sent. Please use the text box to try again.",
        id,
      );
    };
    // boffin: Answers must not wait for the task turn they need to resume.
    if (question) this.questionDispatch = this.questionDispatch.then(dispatch);
    else this.dispatch = this.dispatch.then(dispatch);
  }

  private receive(raw: string, generation: number): void {
    if (generation !== this.generation) return;
    let input: unknown;
    try {
      input = JSON.parse(raw);
    } catch {
      return;
    }
    const parsed = liveVoiceEventSchema.safeParse(input);
    if (!parsed.success) return;
    const event = parsed.data;
    if (event.type === "session.closed") {
      this.seconds = event.usage?.seconds ?? this.seconds;
      this.finish("idle", true);
    } else if (event.type === "session.usage.updated") {
      this.seconds = event.usage.seconds;
    } else if (event.type === "error") {
      this.finish("error");
    } else if (this.state === "closing") {
      return;
    } else if (event.type === "response.event") {
      this.receiveToolEvent(event.event, event.delegation_id, generation);
    } else if (event.type === "session.started") {
      if (this.state !== "connecting") return;
      this.sessionId = event.session.id;
      this.structuredTools = event.session.delegation?.type === "responses";
      this.setState("connected");
      if (this.pendingReply !== null) {
        this.append(this.pendingReply);
        this.pendingReply = null;
      }
      this.syncQuestionContext();
      this.announceQuestion();
      clearTimeout(this.timeout);
      this.timeout = setTimeout(() => this.stop(), 5 * 60_000);
    } else if (event.type === "session.delegation.created") {
      if (event.delegation.target !== "client") return;
      const id = `delegation:${event.delegation.id}`;
      if (this.seen.has(id)) return;
      this.seen.add(id);
      const question = this.question;
      // Transcript delivery can lag the delegation event.
      const timer = setTimeout(() => {
        this.delegationTimers.delete(timer);
        this.delegate(
          event.delegation.id,
          event.offset_ms,
          generation,
          question,
        );
      }, 300);
      this.delegationTimers.add(timer);
    } else {
      if (this.seen.has(event.event_id)) return;
      this.seen.add(event.event_id);
      this.transcripts.push({
        role:
          event.type === "session.input_transcript.delta"
            ? "User"
            : "Voice assistant",
        text: event.delta,
        start: event.start_ms,
        end: event.end_ms,
      });
    }
  }

  async start(): Promise<void> {
    if (this.state !== "idle" && !isVoiceErrorState(this.state)) return;
    const generation = ++this.generation;
    this.seen.clear();
    this.transcripts = [];
    this.pendingReply = null;
    this.dispatch = Promise.resolve();
    this.questionDispatch = Promise.resolve();
    this.toolResponses.clear();
    this.structuredTools = false;
    this.sessionId = null;
    this.seconds = null;
    this.abort = new AbortController();
    this.setState("connecting");
    this.timeout = setTimeout(() => this.finish("error"), 30_000);
    try {
      const offer = await this.transport.createOffer(
        (message) => this.receive(message, generation),
        () => {
          if (generation === this.generation && this.state !== "closing")
            this.finish("error");
        },
        (levels) => {
          if (generation === this.generation && this.state === "connected")
            this.conversation.onAudioLevels?.(levels);
        },
      );
      if (generation !== this.generation) return;
      const answer = await this.conversation.createSession(
        offer,
        this.abort.signal,
      );
      if (generation !== this.generation) return;
      await this.transport.acceptAnswer(answer);
    } catch (error) {
      if (generation !== this.generation) return;
      // boffin: Classify failures because server errors can include private request details.
      if (error instanceof ApiRequestError) this.finish("service-error");
      else if (
        error instanceof Error &&
        ["NotAllowedError", "NotFoundError", "NotReadableError"].includes(
          error.name,
        )
      )
        this.finish("microphone-error");
      else this.finish("error");
    }
  }

  updateReply(text: string, complete: boolean, key = text): void {
    if (!complete || key === this.reply) return;
    this.reply = key;
    // Text and voice share a task. A final task reply can include either input.
    if (this.state === "connecting") this.pendingReply = text;
    else this.append(text);
  }

  stop(): void {
    if (
      this.state === "idle" ||
      isVoiceErrorState(this.state) ||
      this.state === "closing"
    )
      return;
    if (this.state === "connecting") {
      this.finish("idle");
      return;
    }
    this.setState("closing");
    this.transport.mute();
    clearTimeout(this.timeout);
    this.timeout = setTimeout(() => this.finish("idle"), 3_000);
    this.transport.send(JSON.stringify({ type: "session.close" }));
  }

  private finish(state: "idle" | VoiceErrorState, finalized = false): void {
    if (this.state === "idle" || isVoiceErrorState(this.state)) return;
    ++this.generation;
    clearTimeout(this.timeout);
    for (const timer of this.delegationTimers) clearTimeout(timer);
    this.delegationTimers.clear();
    this.toolResponses.clear();
    this.pendingReply = null;
    this.abort?.abort();
    this.transport.close();
    this.conversation.onEnded({
      sessionId: this.sessionId,
      seconds: this.seconds,
      finalized,
      failed: state !== "idle",
    });
    this.setState(state);
  }
}

// Mobile's Metro compiler does not support parameter decorators.
decorate(injectable(), ConversationVoiceSession);
decorate(inject(LIVE_VOICE_TRANSPORT), ConversationVoiceSession, 0);
decorate(inject(VOICE_CONVERSATION), ConversationVoiceSession, 1);
