from __future__ import annotations

from autoevals.llm import LLMClassifier
from braintrust import Score


class CodeQuality(LLMClassifier):
    """LLM judge: evaluate the quality of code changes produced by the agent.

    Assesses readability, correctness, style, and whether the changes are
    minimal and focused (no unnecessary modifications).
    """

    async def _run_eval_async(self, output, expected=None, **kwargs):
        git_diff = output.get("git_diff", "") if output else ""
        if not git_diff:
            return Score(name=self._name(), score=0.0, metadata={"reason": "No code changes"})
        return await super()._run_eval_async(git_diff, expected, **kwargs)

    def _run_eval_sync(self, output, expected=None, **kwargs):
        git_diff = output.get("git_diff", "") if output else ""
        if not git_diff:
            return Score(name=self._name(), score=0.0, metadata={"reason": "No code changes"})
        return super()._run_eval_sync(git_diff, expected, **kwargs)

    def __init__(self, **kwargs):
        super().__init__(
            name="code_quality",
            prompt_template="""You are reviewing code changes (a git diff) produced by an AI coding agent.

Evaluate the quality of these changes:

<code_changes>
{{output}}
</code_changes>

<evaluation_criteria>
1. Correctness: Does the code appear to work correctly? Are there obvious bugs?
2. Readability: Is the code clear and well-structured?
3. Minimality: Are the changes focused on the task, without unnecessary modifications?
4. Style: Does the code follow common conventions for its language?
5. Safety: Are there any security concerns (hardcoded secrets, injection risks, etc.)?
</evaluation_criteria>

Rate the overall code quality. Choose one:
- excellent: Clean, correct, minimal, well-styled code with no issues.
- good: Generally correct and readable with minor style issues.
- acceptable: Works but has some readability or style concerns.
- poor: Has potential bugs, significant style issues, or unnecessary changes.
- bad: Clearly broken, insecure, or completely unreadable.
""".strip(),
            choice_scores={
                "excellent": 1.0,
                "good": 0.8,
                "acceptable": 0.6,
                "poor": 0.3,
                "bad": 0.0,
            },
            model="gpt-4.1",
            max_tokens=1024,
            **kwargs,
        )


class InstructionAdherence(LLMClassifier):
    """LLM judge: does the agent's output faithfully address the given prompt?

    Compares the task prompt against the actual code changes to determine
    whether the agent did what was asked.
    """

    async def _run_eval_async(self, output, expected=None, **kwargs):
        if not output or not output.get("git_diff"):
            return Score(name=self._name(), score=0.0, metadata={"reason": "No code changes"})
        return await super()._run_eval_async(output, expected, **kwargs)

    def _run_eval_sync(self, output, expected=None, **kwargs):
        if not output or not output.get("git_diff"):
            return Score(name=self._name(), score=0.0, metadata={"reason": "No code changes"})
        return super()._run_eval_sync(output, expected, **kwargs)

    def __init__(self, **kwargs):
        super().__init__(
            name="instruction_adherence",
            prompt_template="""You are evaluating whether an AI coding agent correctly followed its instructions.

<task_prompt>
{{input.prompt}}
</task_prompt>

<code_changes>
{{output.git_diff}}
</code_changes>

<files_changed>
{{output.files_changed}}
</files_changed>

<evaluation_criteria>
1. Task completion: Did the agent address the core request in the prompt?
2. Scope: Did the agent stay within the scope of the request, or did it make unrelated changes?
3. Completeness: Did the agent handle all aspects of the request, or only some?
</evaluation_criteria>

Rate how well the agent followed the instructions. Choose one:
- fully_addressed: The agent completely and correctly addressed the prompt.
- mostly_addressed: The agent addressed the main request with minor omissions.
- partially_addressed: The agent made relevant changes but missed significant aspects.
- barely_addressed: The agent made some attempt but largely missed the point.
- not_addressed: The agent's changes are unrelated to the prompt.
""".strip(),
            choice_scores={
                "fully_addressed": 1.0,
                "mostly_addressed": 0.8,
                "partially_addressed": 0.5,
                "barely_addressed": 0.2,
                "not_addressed": 0.0,
            },
            model="gpt-4.1",
            max_tokens=1024,
            **kwargs,
        )


class PRDescriptionQuality(LLMClassifier):
    """LLM judge: evaluate the quality of a PR description (if the agent created one).

    Checks that the PR title is concise, the body explains the changes,
    and the description is useful for reviewers.
    """

    async def _run_eval_async(self, output, expected=None, **kwargs):
        pr_url = output.get("pr_url") if output else None
        if not pr_url:
            return Score(name=self._name(), score=None, metadata={"reason": "No PR created"})
        return await super()._run_eval_async(output, expected, **kwargs)

    def _run_eval_sync(self, output, expected=None, **kwargs):
        pr_url = output.get("pr_url") if output else None
        if not pr_url:
            return Score(name=self._name(), score=None, metadata={"reason": "No PR created"})
        return super()._run_eval_sync(output, expected, **kwargs)

    def __init__(self, **kwargs):
        super().__init__(
            name="pr_description_quality",
            prompt_template="""You are evaluating the quality of a pull request created by an AI coding agent.

<pr_url>
{{output.pr_url}}
</pr_url>

<code_changes_summary>
Files changed: {{output.files_changed}}
Diff size: {{output.git_diff}}
</code_changes_summary>

<agent_output>
{{output.stdout}}
</agent_output>

<evaluation_criteria>
1. Title: Is it concise, descriptive, and under 72 characters?
2. Description: Does it explain what changed and why?
3. Reviewer-friendliness: Would a reviewer understand the changes from the PR description alone?
</evaluation_criteria>

Rate the PR description quality. Choose one:
- excellent: Clear title, thorough description, easy for reviewers.
- good: Decent title and description with minor gaps.
- acceptable: Basic description that conveys the gist.
- poor: Vague or misleading title/description.
- missing: No meaningful description provided.
""".strip(),
            choice_scores={
                "excellent": 1.0,
                "good": 0.8,
                "acceptable": 0.6,
                "poor": 0.3,
                "missing": 0.0,
            },
            model="gpt-4.1",
            max_tokens=1024,
            **kwargs,
        )
