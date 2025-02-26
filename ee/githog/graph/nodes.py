#!/usr/bin/env python3
import os
import time
from github import GithubException, UnknownObjectException
from typing import List, cast, Optional
from pydantic import BaseModel
from github import InputGitTreeElement

from githog.frameworks.main import GITHOG_FRAMEWORK_CONFIGS, get_framework

from ..constants import PR_BODY, PR_TITLE


from ..llm import get_llm
from ..github_utils import get_all_file_paths_in_repo
from githog.graph.state import AgentState
from githog.file_utils import matches_any_pattern
from github import Repository

class RetrieveFilesNode:
    
    repo: Repository.Repository
    def __init__(self, repo: Repository.Repository):
        self.repo = repo

    def run(self, state: AgentState) -> AgentState:
        all_files = get_all_file_paths_in_repo(self.repo, branch=self.repo.default_branch)
        state["all_files"] = all_files
        return state

class DetectFrameworkNode:
    def run(self, state: AgentState) -> AgentState:
        all_files = state.get("all_files", [])
        for framework_config in GITHOG_FRAMEWORK_CONFIGS.values():
            if framework_config.detect(all_files):
                print(f"Detected framework: {framework_config.name.value}")
                state["framework"] = framework_config.name
                break

        if state["framework"] is None:
            raise Exception("No framework detected")
        
            
        
        return state

class FilterFilesNode:
    def run(self, state: AgentState) -> AgentState:

        all_files = state.get("all_files", [])

        framework_name = state.get("framework", None)
        if framework_name is None:
            raise Exception("Framework should be set before filtering files")
        
        framework = get_framework(framework_name)

        print(f"Found {len(all_files)} files in the repository")
        # Select candidate files solely based on the file extension
        candidate_files = [
            f for f in all_files if framework.is_relevant(f)
        ]
        candidate_files_str = "\n".join(candidate_files)
        print(f"Found {len(candidate_files)} candidate files")
        print(f"Candidate files: {candidate_files_str}")
        
        # Set up a prompt that instructs GPT to return output matching the defined format.
        from langchain.prompts import PromptTemplate
        filter_prompt_template = PromptTemplate(
            input_variables=["all_files", "format_instructions", "documentation"],
            template="""
You are a code analysis assistant.
Given the following list of Next.js file paths from a project, determine which files are likely to require modifications 
to integrate PostHog. Use the installation documentation as a reference for what files might need modifications, do not include files that are unlikely to require modification based on the documentation.

- If you would like to create a new file, you can include the file path in your response.
- If you would like to modify an existing file, you can include the file path in your response.

You should return all files that you think will be required to look at or modify to integrate PostHog. You should return them in the order you would like to see them processed, with new files first, followed by the files that you want to update to integrate PostHog.

Rules:
- Only return files that you think will be required to look at or modify to integrate PostHog.
- Do not return files that are unlikely to require modification based on the documentation.
- If you are unsure, return the file.
- If you create a new file, it should not conflict with any existing files.
- If the user is using TypeScript, you should return .ts and .tsx files.
- You should implement both posthog-js and posthog-node.

Installation documentation:
{documentation}

All current files in the repository:

{file_list}
""",
        )

        formatted_prompt = filter_prompt_template.format(
            documentation=framework.config.installation_instructions,
            file_list=candidate_files_str,
        )

        class FilterFilesOutput(BaseModel):
            relevant_files: List[str]            

        llm = get_llm()

        structured_llm = llm.with_structured_output(FilterFilesOutput)
        
        response = cast(FilterFilesOutput, structured_llm.invoke(formatted_prompt))

        selected_files = response.relevant_files

        include_files = [f for f in state["all_files"] if matches_any_pattern(f, framework.config.include_patterns)]

        create_files = framework.config.create_patterns

        relevant_files = list(set(selected_files + include_files + create_files))

        state["relevant_files"] = relevant_files
        

        print(f"Found {len(state['relevant_files'])} relevant files: {state['relevant_files']}")
        return state

class GenerateFileChangeNode:
    def __init__(self, repo: Repository.Repository):
        self.repo = repo

    def run(self, state: AgentState, file_path: str) -> AgentState:

        framework_name = state.get("framework", None)
        if framework_name is None:
            raise Exception("Framework should be set before generating a file change")
        
        framework = get_framework(framework_name)

        try:
            file_obj = self.repo.get_contents(file_path)
            file_content = file_obj.decoded_content.decode("utf-8")
            file_sha = cast(str, file_obj.sha)

            def add_line_numbers(text: str) -> str:
                return "\n".join(f"{i+1:4d}: {line}" for i, line in enumerate(text.splitlines()))
            
            numbered_file_content = add_line_numbers(file_content)
            print(f"File content for {file_path} (with line numbers):\n{numbered_file_content}")
            if isinstance(file_obj, list):
                file_obj = file_obj[0]
        except UnknownObjectException:
            file_content = ""
            file_sha = None
            numbered_file_content = ""




        from langchain.prompts import PromptTemplate

        # Build a prompt that instructs the LLM to return the full updated file.
        file_change_prompt_template = PromptTemplate(
            input_variables=["numbered_file_content", "documentation"],
            template="""
You are GitHog, a master AI programming assistant that implements PostHog for Next.js projects.

Your task is to update the file to integrate PostHog according to the documentation.
Do not return a diff—return the complete updated file content.
Follow these rules:
- Preserve the existing code formatting and style.
- Only make the changes required by the documentation.
- If no changes are needed, return the file as-is.
- Line numbers in the provided file content are for reference only and should not appear in the output.
- If the current file is empty, and you think it should be created, you can add the contents of the new file.


CONTEXT
---
posthog-js latest version: 1.222.0
posthog-node latest version: 4.7.0

Documentation for integrating PostHog with Next.js:
{documentation}

The file you are updating is:
{file_path}

You have already made changes to the following files:
{changes}

Below is the current file content with line numbers:
{numbered_file_content}
""",
        )

        formatted_prompt = file_change_prompt_template.format(
            numbered_file_content=numbered_file_content,
            file_path=file_path,
            changes=state.get("changes", []),
            documentation=framework.config.installation_instructions
        )

        class FileChangeOutput(BaseModel):
            updated_file: Optional[str] = None

        llm = get_llm()

        structured_llm = llm.with_structured_output(FileChangeOutput)
        response = structured_llm.invoke(formatted_prompt)
        updated_file = response.updated_file

        print(f"Updated file for {file_path}:\n{updated_file}")

        if not updated_file or updated_file.strip() == file_content.strip():
            print(f"No changes made to {file_path}")
            return state

        state["changes"].append({
            "file_path": file_path,
            "new_content": updated_file,
            "old_sha": file_sha,
        })

        return state

class CommitFilesNode:
    def __init__(self, repo: Repository.Repository):
        self.repo = repo

    def run(self, state: AgentState) -> AgentState:
        changes = state.get("changes", [])
        if not changes:
            print("No changes to commit.")
            return state

        branch_name = f"posthog-integration-{int(time.time())}"
        base_branch = self.repo.default_branch

        base_ref = self.repo.get_git_ref(f"heads/{base_branch}")
        base_commit = self.repo.get_git_commit(base_ref.object.sha)
        base_sha = base_commit.sha
        base_tree = base_commit.tree

        print(f"Base Commit SHA: {base_sha}")

        try:
            self.repo.create_git_ref(ref=f"refs/heads/{branch_name}", sha=base_sha)
            print(f"Created branch {branch_name}")
        except GithubException as e:
            print(f"Error creating branch: {e}")
            return state

        tree_elements = []
        for change in changes:
            file_path = change["file_path"]
            new_content = change["new_content"]
            try:
                blob = self.repo.create_git_blob(new_content, "utf-8")
            except GithubException as e:
                print(f"Error creating blob for {file_path}: {e}")
                continue
            element = InputGitTreeElement(
                path=file_path,
                mode="100644",
                type="blob",
                sha=blob.sha,
            )
            tree_elements.append(element)

        if not tree_elements:
            print("No valid tree elements created; aborting commit.")
            return state

        try:
            new_tree = self.repo.create_git_tree(tree_elements, base_tree=base_tree)
        except GithubException as e:
            print(f"Error creating new tree: {e}")
            return state

        commit_message = "PostHog integration via GitHog"
        try:
            new_commit = self.repo.create_git_commit(commit_message, new_tree, [base_commit])
        except GithubException as e:
            print(f"Error creating commit: {e}")
            return state

        try:
            new_branch_ref = self.repo.get_git_ref(f"heads/{branch_name}")
            new_branch_ref.edit(new_commit.sha)
            print("Updated branch reference to new commit.")
        except GithubException as e:
            print(f"Error updating branch reference: {e}")
            return state

        state["branch"] = branch_name
        state["committed"] = True
        return state


# Node: Create a pull request.
class CreatePRNode:
    def __init__(self, repo: Repository.Repository):
        self.repo = repo

    def run(self, state: AgentState) -> AgentState:
        branch = state.get("branch")
        changes = state.get("changes", [])

        if not branch or not changes:
            print("No committed changes; skipping PR creation.")
            return state
        
        framework_name = state.get("framework", None)
        if framework_name is None:
            raise Exception("Framework should be set before creating a PR")
        
        framework = get_framework(framework_name)

        pr_title = PR_TITLE
        pr_body = PR_BODY.format(pr_instructions=framework.config.pr_instructions)

        try:
            # Create the pull request
            pr = self.repo.create_pull(
                title=pr_title, body=pr_body, head=branch, base=self.repo.default_branch
            )
            state["pr_url"] = pr.html_url
            print(f"Pull Request created: {pr.html_url}")

            # Extract repository owner from REPO_NAME (format: "owner/repo")
            repo_name = os.getenv("REPO_NAME")  # Example: "username/repo-name"
            if not repo_name or "/" not in repo_name:
                print("Error: REPO_NAME environment variable is missing or incorrectly formatted.")
                return state

            repo_owner = repo_name.split("/")[0]  # Extract the owner (first part)
            print(f"Requesting review from repository owner: {repo_owner}")

            # Request a review from the repository owner
            pr.create_review_request(reviewers=[repo_owner])
            print(f"Review requested from {repo_owner}")

        except GithubException as e:
            print(f"Error creating pull request or requesting review: {e}")

        return state